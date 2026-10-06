from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.inventario.models import ProductoInventario
from apps.usuarios.models import RegistroAuditoria

from .models import Abono, Cliente, DetalleVenta, Venta


class VentaError(ValueError):
    """Error de validación del flujo de ventas."""


def _auditar(usuario, accion, request=None):
    RegistroAuditoria.objects.create(
        usuario=usuario,
        accion=accion[:255],
        modulo='Ventas',
        ip_origen=request.META.get('REMOTE_ADDR') if request else None,
    )


def _normalizar_articulos(articulos):
    cantidades = {}
    if not isinstance(articulos, (list, tuple)):
        raise VentaError('La lista de artículos no es válida.')
    for articulo in articulos:
        if not isinstance(articulo, dict):
            raise VentaError('Selecciona productos y cantidades válidas.')
        try:
            producto_id = int(articulo['producto_id'])
            cantidad = int(articulo['cantidad'])
        except (KeyError, TypeError, ValueError):
            raise VentaError('Selecciona productos y cantidades válidas.')
        if cantidad <= 0:
            raise VentaError('La cantidad de cada producto debe ser mayor que cero.')
        cantidades[producto_id] = cantidades.get(producto_id, 0) + cantidad
    if not cantidades:
        raise VentaError('Agrega al menos un producto a la venta.')
    return cantidades


def _bloquear_productos(*, sede_id, articulos):
    cantidades = _normalizar_articulos(articulos)
    productos = list(
        ProductoInventario.objects.select_for_update()
        .filter(pk__in=sorted(cantidades))
        .order_by('pk')
    )
    productos_por_id = {producto.pk: producto for producto in productos}
    if len(productos_por_id) != len(cantidades):
        raise VentaError('Uno o más productos ya no están disponibles.')

    for producto_id, cantidad in cantidades.items():
        producto = productos_por_id[producto_id]
        if producto.sede_id != sede_id:
            raise VentaError(f'El producto {producto.nombre} no pertenece a la sede seleccionada.')
        if producto.cantidad < cantidad:
            raise VentaError(
                f'Stock insuficiente para {producto.nombre}. Disponible: {producto.cantidad}.'
            )
    return cantidades, productos_por_id


def _descontar_productos(*, venta, cantidades, productos_por_id):
    ahora = timezone.now()
    for producto_id, cantidad in cantidades.items():
        producto = productos_por_id[producto_id]
        precio = producto.precio
        DetalleVenta.objects.create(
            venta=venta,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=precio,
            subtotal=precio * cantidad,
        )
        producto.cantidad -= cantidad
        producto.fecha_actualizacion = ahora
        producto.save(update_fields=['cantidad', 'fecha_actualizacion'])


@transaction.atomic
def crear_venta(*, cliente_id=None, datos_cliente=None, vendedor, sede, tipo_pago, articulos, request=None):
    if tipo_pago not in dict(Venta.TIPOS_PAGO):
        raise VentaError('Selecciona un tipo de pago válido.')
    if not sede.activa:
        raise VentaError('No se pueden registrar ventas en una sede inactiva.')
    if vendedor.rol != 'ADMIN' and vendedor.sede_id != sede.pk:
        raise VentaError('Solo puedes registrar ventas en tu sede asignada.')

    if cliente_id:
        try:
            cliente = Cliente.objects.get(pk=cliente_id)
        except (Cliente.DoesNotExist, ValueError):
            raise VentaError('El cliente seleccionado ya no existe. Búscalo nuevamente.')
    else:
        datos_cliente = datos_cliente or {}
        cedula = (datos_cliente.get('cedula_o_rif') or '').strip()
        nombre = (datos_cliente.get('nombre_completo') or '').strip()
        if not cedula or not nombre:
            raise VentaError('Busca un cliente o completa su identificación y nombre.')
        cliente, creado = Cliente.objects.get_or_create(
            cedula_o_rif=cedula,
            defaults={
                'nombre_completo': nombre,
                'telefono': (datos_cliente.get('telefono') or '').strip() or None,
                'direccion': (datos_cliente.get('direccion') or '').strip() or None,
            },
        )
        if not creado and cliente.nombre_completo.casefold() != nombre.casefold():
            raise VentaError('La identificación ya está registrada con otro nombre. Selecciona el cliente existente.')

    cantidades, productos_por_id = _bloquear_productos(sede_id=sede.pk, articulos=articulos)

    venta = Venta.objects.create(
        cliente=cliente,
        vendedor=vendedor,
        sede=sede,
        tipo_pago=tipo_pago,
        estado=Venta.PENDIENTE if tipo_pago == Venta.FIADO else Venta.PAGADA,
    )
    _descontar_productos(
        venta=venta,
        cantidades=cantidades,
        productos_por_id=productos_por_id,
    )
    _auditar(
        vendedor,
        f'Registró venta al {venta.tipo_pago} por {venta.calcular_total()} (Cliente: {cliente.nombre_completo})',
        request,
    )
    return venta


@transaction.atomic
def agregar_articulos_fiados(*, venta_id, articulos, usuario, request=None):
    venta = Venta.objects.select_for_update().select_related('cliente').get(pk=venta_id)
    if venta.tipo_pago != Venta.FIADO or venta.estado != Venta.PENDIENTE:
        raise VentaError('Solo puedes agregar artículos a una venta fiada pendiente.')
    if usuario.rol != 'ADMIN' and usuario.sede_id != venta.sede_id:
        raise VentaError('Solo puedes agregar artículos desde la sede donde se abrió la venta.')
    if usuario.rol != 'ADMIN' and not usuario.sede.activa:
        raise VentaError('La sede asignada al usuario está inactiva.')
    cantidades, productos_por_id = _bloquear_productos(sede_id=venta.sede_id, articulos=articulos)
    _descontar_productos(
        venta=venta,
        cantidades=cantidades,
        productos_por_id=productos_por_id,
    )
    venta.fecha_actualizacion = timezone.now()
    venta.save(update_fields=['fecha_actualizacion'])
    _auditar(usuario, f'Agregó artículos a la venta fiada #{venta.pk} (Cliente: {venta.cliente.nombre_completo})', request)
    return venta


@transaction.atomic
def registrar_abono(*, venta_id, monto, metodo_pago, cajero, sede_donde_paga, request=None):
    venta = Venta.objects.select_for_update().select_related('cliente').get(pk=venta_id)
    if venta.tipo_pago != Venta.FIADO or venta.estado != Venta.PENDIENTE:
        raise VentaError('Esta venta no tiene una deuda pendiente.')
    if not sede_donde_paga.activa:
        raise VentaError('No se pueden recibir pagos en una sede inactiva.')
    if cajero.rol != 'ADMIN' and cajero.sede_id != sede_donde_paga.pk:
        raise VentaError('El abono debe registrarse en la sede asignada al cajero.')

    try:
        monto = Decimal(str(monto))
    except (InvalidOperation, TypeError, ValueError):
        raise VentaError('Ingresa un monto válido.')
    if monto <= 0:
        raise VentaError('El abono debe ser mayor que cero.')

    saldo = venta.calcular_saldo_deudor()
    if monto > saldo:
        raise VentaError(f'El abono supera el saldo pendiente de {saldo}.')

    abono = Abono.objects.create(
        venta=venta,
        monto=monto,
        metodo_pago=metodo_pago,
        cajero=cajero,
        sede_donde_paga=sede_donde_paga,
    )
    if venta.calcular_saldo_deudor() == 0:
        venta.estado = Venta.PAGADA
    venta.fecha_actualizacion = timezone.now()
    venta.save(update_fields=['estado', 'fecha_actualizacion'])
    _auditar(
        cajero,
        f'Registró abono de {abono.monto} a Venta #{venta.pk} (Cliente: {venta.cliente.nombre_completo})',
        request,
    )
    return abono
