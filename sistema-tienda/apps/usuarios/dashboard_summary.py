from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.inventario.models import ProductoInventario
from apps.usuarios.models import Sede
from apps.ventas.models import Abono, DetalleVenta, Venta


def construir_resumen_operaciones(usuario, sede_id=None):
    es_admin = usuario.rol == 'ADMIN'
    sedes_activas = Sede.objects.filter(activa=True).order_by('nombre')
    sede_seleccionada = None

    ventas = Venta.objects.all()
    if es_admin:
        if str(sede_id or '').isdigit():
            sede_seleccionada = sedes_activas.filter(pk=int(sede_id)).first()
        inventario = ProductoInventario.objects.filter(sede__activa=True)
        if sede_seleccionada:
            ventas = ventas.filter(sede=sede_seleccionada)
            inventario = inventario.filter(sede=sede_seleccionada)
        alcance = sede_seleccionada.nombre if sede_seleccionada else 'Todas las sedes'
    else:
        sede_seleccionada = sedes_activas.filter(pk=usuario.sede_id).first() if usuario.sede_id else None
        if sede_seleccionada:
            ventas = ventas.filter(sede=sede_seleccionada)
            inventario = ProductoInventario.objects.filter(sede=sede_seleccionada)
            alcance = sede_seleccionada.nombre
        else:
            ventas = ventas.none()
            inventario = ProductoInventario.objects.none()
            alcance = 'Sin sede activa asignada'

    hoy = timezone.localdate()
    inicio_hoy = timezone.make_aware(datetime.combine(hoy, time.min))
    inicio_manana = timezone.make_aware(datetime.combine(hoy + timedelta(days=1), time.min))
    ventas_hoy = ventas.filter(fecha_apertura__gte=inicio_hoy, fecha_apertura__lt=inicio_manana)
    facturado_hoy = DetalleVenta.objects.filter(venta__in=ventas_hoy).aggregate(
        total=Sum('subtotal'),
    )['total'] or Decimal('0.00')

    deudas_pendientes = Venta.objects.filter(tipo_pago=Venta.FIADO, estado=Venta.PENDIENTE)
    ids_deudas = deudas_pendientes.values('pk')
    total_deuda = DetalleVenta.objects.filter(venta__in=ids_deudas).aggregate(
        total=Sum('subtotal'),
    )['total'] or Decimal('0.00')
    total_abonos = Abono.objects.filter(venta__in=ids_deudas).aggregate(
        total=Sum('monto'),
    )['total'] or Decimal('0.00')
    saldo_global = max(total_deuda - total_abonos, Decimal('0.00'))

    primer_dia = hoy - timedelta(days=6)
    inicio_semana = timezone.make_aware(datetime.combine(primer_dia, time.min))
    ventas_semana = ventas.filter(fecha_apertura__gte=inicio_semana, fecha_apertura__lt=inicio_manana)
    ventas_por_dia = {
        fila['dia']: fila['total']
        for fila in DetalleVenta.objects.filter(venta__in=ventas_semana)
        .annotate(dia=TruncDate('venta__fecha_apertura', tzinfo=timezone.get_current_timezone()))
        .values('dia')
        .annotate(total=Sum('subtotal'))
    }
    total_diario = [ventas_por_dia.get(primer_dia + timedelta(days=indice), Decimal('0.00')) for indice in range(7)]
    maximo_diario = max(total_diario, default=Decimal('0.00'))
    actividad_semanal = [
        {
            'fecha': primer_dia + timedelta(days=indice),
            'total': total,
            'porcentaje': max(4, int(total * 100 / maximo_diario)) if maximo_diario else 4,
        }
        for indice, total in enumerate(total_diario)
    ]

    agotados = inventario.filter(cantidad=0)
    productos_agotados = list(agotados.select_related('sede').order_by('nombre')[:6])
    ventas_recientes = list(
        ventas.select_related('cliente', 'sede')
        .prefetch_related('detalles')
        .order_by('-fecha_apertura', '-pk')[:8]
    )

    return {
        'es_admin': es_admin,
        'sedes': sedes_activas if es_admin else (),
        'sede_seleccionada': sede_seleccionada,
        'alcance': alcance,
        'ventas_hoy': ventas_hoy.count(),
        'facturado_hoy': facturado_hoy,
        'deudas_pendientes': deudas_pendientes.count(),
        'saldo_global': saldo_global,
        'productos_agotados_total': agotados.count(),
        'productos_agotados': productos_agotados,
        'actividad_semanal': actividad_semanal,
        'ventas_recientes': ventas_recientes,
    }