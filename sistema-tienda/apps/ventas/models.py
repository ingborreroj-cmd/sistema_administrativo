from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum

from apps.inventario.models import ProductoInventario
from apps.usuarios.models import Sede, Usuario


class Cliente(models.Model):
    cedula_o_rif = models.CharField(max_length=20, unique=True)
    nombre_completo = models.CharField(max_length=150)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    direccion = models.TextField(blank=True, null=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre_completo', 'id']

    def __str__(self):
        return f'{self.nombre_completo} - {self.cedula_o_rif}'


class Venta(models.Model):
    CONTADO = 'CONTADO'
    FIADO = 'FIADO'
    PAGADA = 'PAGADA'
    PENDIENTE = 'PENDIENTE'
    CANCELADA = 'CANCELADA'

    TIPOS_PAGO = (
        (CONTADO, 'Pago al contado'),
        (FIADO, 'Crédito / fiado'),
    )
    ESTADOS = (
        (PAGADA, 'Pagada totalmente'),
        (PENDIENTE, 'Pendiente por pagar'),
        (CANCELADA, 'Cancelada'),
    )

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='ventas')
    vendedor = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='ventas_realizadas')
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='ventas')
    tipo_pago = models.CharField(max_length=10, choices=TIPOS_PAGO, default=CONTADO)
    estado = models.CharField(max_length=15, choices=ESTADOS, default=PAGADA)
    fecha_apertura = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_apertura', '-id']
        indexes = [
            models.Index(fields=['sede', 'fecha_apertura'], name='ventas_sede_fecha_idx'),
            models.Index(fields=['tipo_pago', 'estado'], name='ventas_pago_estado_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(tipo_pago='CONTADO', estado='PAGADA')
                    | Q(tipo_pago='FIADO', estado__in=['PAGADA', 'PENDIENTE'])
                    | Q(estado='CANCELADA')
                ),
                name='ventas_estado_pago_coherente',
            ),
        ]

    def calcular_total(self):
        detalles = getattr(self, '_prefetched_objects_cache', {}).get('detalles')
        if detalles is not None:
            return sum((detalle.subtotal for detalle in detalles), Decimal('0.00'))
        total = self.detalles.aggregate(total=Sum('subtotal'))['total']
        return total or Decimal('0.00')

    def calcular_saldo_deudor(self):
        abonos = getattr(self, '_prefetched_objects_cache', {}).get('abonos')
        if abonos is not None:
            total_abonos = sum((abono.monto for abono in abonos), Decimal('0.00'))
        else:
            total_abonos = self.abonos.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        return max(self.calcular_total() - total_abonos, Decimal('0.00'))

    def __str__(self):
        return f'Venta #{self.pk} - {self.cliente.nombre_completo} ({self.tipo_pago})'


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(ProductoInventario, on_delete=models.PROTECT, related_name='detalles_venta')
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name='ventas_detalle_cantidad_positiva'),
            models.CheckConstraint(condition=Q(precio_unitario__gte=0), name='ventas_detalle_precio_no_negativo'),
            models.CheckConstraint(condition=Q(subtotal__gte=0), name='ventas_detalle_subtotal_no_negativo'),
        ]

    def __str__(self):
        return f'{self.cantidad} x {self.producto.nombre} - Venta #{self.venta_id}'


class Abono(models.Model):
    PUNTO_DE_VENTA = 'PUNTO_DE_VENTA'
    PAGO_MOVIL = 'PAGO_MOVIL'

    METODOS_PAGO = (
        (PUNTO_DE_VENTA, 'Punto de venta'),
        (PAGO_MOVIL, 'Pago móvil'),
    )

    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='abonos')
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    fecha = models.DateTimeField(auto_now_add=True)
    metodo_pago = models.CharField(max_length=20, choices=METODOS_PAGO)
    cajero = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='abonos_registrados')
    sede_donde_paga = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='abonos_recibidos')

    class Meta:
        ordering = ['-fecha', '-id']
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name='ventas_abono_monto_positivo'),
        ]

    def __str__(self):
        return f'Abono {self.monto} a Venta #{self.venta_id}'


class Devolucion(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name='devoluciones')
    producto = models.ForeignKey(ProductoInventario, on_delete=models.PROTECT, related_name='devoluciones')
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    motivo = models.CharField(max_length=120, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    cajero = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='devoluciones_registradas')
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='devoluciones')

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'Devolución de {self.cantidad} x {self.producto.nombre} a Venta #{self.venta_id}'


class VentaEvento(models.Model):
    CANCELACION = 'CANCELACION'
    DEVOLUCION = 'DEVOLUCION'

    TIPOS_EVENTO = (
        (CANCELACION, 'Cancelación de venta'),
        (DEVOLUCION, 'Devolución de venta'),
    )

    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name='eventos')
    tipo_evento = models.CharField(max_length=20, choices=TIPOS_EVENTO)
    producto = models.ForeignKey(
        ProductoInventario,
        on_delete=models.PROTECT,
        related_name='eventos_venta',
        null=True,
        blank=True,
    )
    cantidad = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    motivo = models.CharField(max_length=180, blank=True, default='')
    monto_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='eventos_venta')
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='eventos_venta')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-id']
        indexes = [
            models.Index(fields=['tipo_evento', 'fecha'], name='venta_evento_tipo_fecha_idx'),
            models.Index(fields=['venta', 'tipo_evento'], name='venta_evento_venta_tipo_idx'),
        ]

    def __str__(self):
        nombre = self.producto.nombre if self.producto else 'Venta'
        return f'{self.get_tipo_evento_display()} - {nombre} ({self.venta_id})'
