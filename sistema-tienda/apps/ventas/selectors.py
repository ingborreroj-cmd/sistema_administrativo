from datetime import datetime
from decimal import Decimal

from django.db.models import Q, Sum

from .models import DetalleVenta, Venta


def ventas_filtradas(*, usuario, parametros, incluir_otras_sedes=False):
    ventas = Venta.objects.select_related('cliente', 'vendedor', 'sede').prefetch_related('detalles', 'abonos')
    if not incluir_otras_sedes and usuario.rol != 'ADMIN':
        ventas = ventas.filter(sede_id=usuario.sede_id) if usuario.sede_id else ventas.none()

    busqueda = parametros.get('q', '').strip()
    sede_id = parametros.get('sede', '').strip()
    desde = parametros.get('desde', '').strip()
    hasta = parametros.get('hasta', '').strip()
    if busqueda:
        filtro = Q(cliente__nombre_completo__icontains=busqueda) | Q(cliente__cedula_o_rif__icontains=busqueda)
        if busqueda.isdigit():
            filtro |= Q(pk=int(busqueda))
        ventas = ventas.filter(filtro)
    if usuario.rol == 'ADMIN' and sede_id.isdigit():
        ventas = ventas.filter(sede_id=int(sede_id))
    if desde:
        try:
            fecha = datetime.strptime(desde, '%Y-%m-%d').date()
            ventas = ventas.filter(fecha_apertura__date__gte=fecha)
        except ValueError:
            desde = ''
    if hasta:
        try:
            fecha = datetime.strptime(hasta, '%Y-%m-%d').date()
            ventas = ventas.filter(fecha_apertura__date__lte=fecha)
        except ValueError:
            hasta = ''
    return ventas, {'q': busqueda, 'sede': sede_id, 'desde': desde, 'hasta': hasta}


def obtener_total_facturado(ventas):
    total = DetalleVenta.objects.filter(
        venta__in=ventas.order_by().values('pk'),
    ).aggregate(total=Sum('subtotal'))['total']
    return total or Decimal('0.00')
