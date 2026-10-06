from django.contrib import admin

from .models import Abono, Cliente, DetalleVenta, Venta


class DetalleVentaInline(admin.TabularInline):
    model = DetalleVenta
    extra = 0
    readonly_fields = ['producto', 'cantidad', 'precio_unitario', 'subtotal']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AbonoInline(admin.TabularInline):
    model = Abono
    extra = 0
    readonly_fields = ['monto', 'fecha', 'metodo_pago', 'cajero', 'sede_donde_paga']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'cedula_o_rif', 'telefono', 'fecha_registro']
    search_fields = ['nombre_completo', 'cedula_o_rif', 'telefono']


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ['id', 'cliente', 'sede', 'vendedor', 'tipo_pago', 'estado', 'fecha_apertura']
    list_filter = ['tipo_pago', 'estado', 'sede', 'fecha_apertura']
    search_fields = ['cliente__nombre_completo', 'cliente__cedula_o_rif']
    readonly_fields = [
        'cliente', 'vendedor', 'sede', 'tipo_pago', 'estado',
        'fecha_apertura', 'fecha_actualizacion',
    ]
    inlines = [DetalleVentaInline, AbonoInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ['venta', 'monto', 'metodo_pago', 'cajero', 'sede_donde_paga', 'fecha']
    list_filter = ['metodo_pago', 'sede_donde_paga', 'fecha']
    search_fields = ['venta__cliente__nombre_completo', 'venta__cliente__cedula_o_rif']
    readonly_fields = ['venta', 'monto', 'fecha', 'metodo_pago', 'cajero', 'sede_donde_paga']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
