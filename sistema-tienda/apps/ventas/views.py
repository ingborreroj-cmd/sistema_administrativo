import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.inventario.models import ProductoInventario
from apps.usuarios.models import Sede

from .forms import AbonoForm, VentaForm
from .models import Cliente, Venta
from .reports import exportar_excel, exportar_pdf
from .selectors import obtener_total_facturado, ventas_filtradas
from .services import VentaError, agregar_articulos_fiados, crear_venta, registrar_abono


def _sedes_usuario(usuario):
    if usuario.rol == 'ADMIN':
        return Sede.objects.filter(activa=True).order_by('nombre')
    if usuario.sede_id:
        return Sede.objects.filter(pk=usuario.sede_id, activa=True)
    return Sede.objects.none()


@login_required
def historial_ventas(request):
    ventas, filtros = ventas_filtradas(usuario=request.user, parametros=request.GET)
    total_facturado = obtener_total_facturado(ventas)
    exportar = request.GET.get('exportar')
    if exportar == 'excel':
        return exportar_excel(ventas, total_facturado)
    if exportar == 'pdf':
        return exportar_pdf(ventas, total_facturado)
    pagina = Paginator(ventas, 50).get_page(request.GET.get('page'))
    return render(request, 'ventas/historial.html', {
        'ventas': pagina,
        'pagina': pagina,
        'total_facturado': total_facturado,
        'sedes': _sedes_usuario(request.user),
        'filtros': filtros,
    })


@login_required
def nueva_venta(request):
    sedes = _sedes_usuario(request.user)
    if not sedes.exists():
        messages.error(request, 'Necesitas una sede activa asignada para registrar ventas.')
        return redirect('inventario:lista_productos')

    if request.method == 'POST':
        form = VentaForm(request.POST, sedes=sedes)
        articulos_json = request.POST.get('articulos', '[]')
        if form.is_valid():
            try:
                articulos = json.loads(articulos_json)
                cliente_data = {
                    'cedula_o_rif': form.cleaned_data['cedula_o_rif'],
                    'nombre_completo': form.cleaned_data['nombre_completo'],
                    'telefono': form.cleaned_data['telefono'],
                    'direccion': form.cleaned_data['direccion'],
                }
                venta = crear_venta(
                    cliente_id=form.cleaned_data['cliente_id'],
                    datos_cliente=cliente_data,
                    vendedor=request.user,
                    sede=form.cleaned_data['sede'],
                    tipo_pago=form.cleaned_data['tipo_pago'],
                    articulos=articulos,
                    request=request,
                )
            except (json.JSONDecodeError, VentaError) as error:
                form.add_error(None, str(error) if not isinstance(error, json.JSONDecodeError) else 'Los productos enviados no son válidos.')
            else:
                messages.success(request, f'Venta #{venta.pk} registrada correctamente.')
                return redirect('ventas:detalle_venta', pk=venta.pk)
    else:
        initial = {'sede': request.user.sede_id} if request.user.rol != 'ADMIN' else {
            'sede': request.GET.get('sede') or None,
        }
        form = VentaForm(sedes=sedes, initial=initial)

    productos = []
    sede_seleccionada = request.POST.get('sede') or request.GET.get('sede') or (
        request.user.sede_id if request.user.rol != 'ADMIN' else None
    )
    if str(sede_seleccionada).isdigit():
        productos = list(
            ProductoInventario.objects
            .filter(sede_id=sede_seleccionada, cantidad__gt=0)
            .order_by('nombre')
            .values('id', 'nombre', 'precio', 'cantidad')
        )
    return render(request, 'ventas/nueva_venta.html', {
        'form': form,
        'productos': productos,
        'sedes': sedes,
    })


@login_required
def buscar_clientes(request):
    query = request.GET.get('q', '').strip()[:80]
    clientes = Cliente.objects.none()
    if len(query) >= 2:
        clientes = Cliente.objects.filter(
            Q(nombre_completo__icontains=query) | Q(cedula_o_rif__icontains=query)
        ).order_by('nombre_completo')[:10]
    return JsonResponse({'clientes': [
        {
            'id': cliente.pk,
            'nombre': cliente.nombre_completo,
            'identificacion': cliente.cedula_o_rif,
            'telefono': cliente.telefono or '',
            'direccion': cliente.direccion or '',
        }
        for cliente in clientes
    ]})


@login_required
def detalle_venta(request, pk):
    venta = get_object_or_404(
        Venta.objects.select_related('cliente', 'vendedor', 'sede').prefetch_related('detalles__producto', 'abonos__cajero', 'abonos__sede_donde_paga'),
        pk=pk,
    )
    puede_ver_global = venta.tipo_pago == Venta.FIADO and venta.estado == Venta.PENDIENTE
    if request.user.rol != 'ADMIN' and venta.sede_id != request.user.sede_id and not puede_ver_global:
        get_object_or_404(Venta.objects.none(), pk=pk)

    puede_agregar = (
        venta.tipo_pago == Venta.FIADO
        and venta.estado == Venta.PENDIENTE
        and (request.user.rol == 'ADMIN' or venta.sede_id == request.user.sede_id)
    )
    productos = []
    if puede_agregar:
        productos = ProductoInventario.objects.filter(sede=venta.sede, cantidad__gt=0).order_by('nombre')

    return render(request, 'ventas/detalle_venta.html', {
        'venta': venta,
        'saldo': venta.calcular_saldo_deudor(),
        'total': venta.calcular_total(),
        'puede_agregar': puede_agregar,
        'productos': productos,
    })


@login_required
def agregar_articulos(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    if request.user.rol != 'ADMIN' and venta.sede_id != request.user.sede_id:
        messages.error(request, 'Solo la sede donde se abrió la venta puede agregar artículos.')
        return redirect('ventas:detalle_venta', pk=pk)
    if request.method != 'POST':
        return redirect('ventas:detalle_venta', pk=pk)
    try:
        articulos = json.loads(request.POST.get('articulos', '[]'))
        agregar_articulos_fiados(venta_id=pk, articulos=articulos, usuario=request.user, request=request)
    except (json.JSONDecodeError, VentaError) as error:
        messages.error(request, str(error) if not isinstance(error, json.JSONDecodeError) else 'Los productos enviados no son válidos.')
    else:
        messages.success(request, 'Artículos agregados y stock actualizado.')
    return redirect('ventas:detalle_venta', pk=pk)


@login_required
def cuentas_por_cobrar(request):
    ventas, filtros = ventas_filtradas(
        usuario=request.user,
        parametros=request.GET,
        incluir_otras_sedes=True,
    )
    ventas = ventas.filter(tipo_pago=Venta.FIADO, estado=Venta.PENDIENTE)
    pagina = Paginator(ventas, 50).get_page(request.GET.get('page'))
    return render(request, 'ventas/cuentas_por_cobrar.html', {
        'ventas': pagina,
        'pagina': pagina,
        'sedes': _sedes_usuario(request.user),
        'filtros': filtros,
    })


@login_required
def registrar_abono_view(request, pk):
    venta = get_object_or_404(
        Venta.objects.select_related('cliente', 'sede').prefetch_related('detalles', 'abonos'),
        pk=pk,
        tipo_pago=Venta.FIADO,
        estado=Venta.PENDIENTE,
    )
    sedes = _sedes_usuario(request.user)
    if not sedes.exists():
        messages.error(request, 'Necesitas una sede activa para recibir un abono.')
        return redirect('ventas:cuentas_por_cobrar')

    if request.method == 'POST':
        form = AbonoForm(request.POST, sedes=sedes)
        if form.is_valid():
            try:
                abono = registrar_abono(
                    venta_id=venta.pk,
                    monto=form.cleaned_data['monto'],
                    metodo_pago=form.cleaned_data['metodo_pago'],
                    cajero=request.user,
                    sede_donde_paga=form.cleaned_data['sede_donde_paga'],
                    request=request,
                )
            except VentaError as error:
                form.add_error(None, str(error))
            else:
                messages.success(request, f'Abono de ${abono.monto:.2f} registrado.')
                return redirect('ventas:detalle_venta', pk=venta.pk)
    else:
        initial = {'sede_donde_paga': request.user.sede_id} if request.user.rol != 'ADMIN' else None
        form = AbonoForm(sedes=sedes, initial=initial)

    return render(request, 'ventas/registrar_abono.html', {
        'form': form,
        'venta': venta,
        'saldo': venta.calcular_saldo_deudor(),
    })
