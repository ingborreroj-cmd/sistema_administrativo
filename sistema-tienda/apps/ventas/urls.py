from django.urls import path

from . import views

app_name = 'ventas'

urlpatterns = [
    path('', views.historial_ventas, name='historial'),
    path('nueva/', views.nueva_venta, name='nueva_venta'),
    path('clientes/buscar/', views.buscar_clientes, name='buscar_clientes'),
    path('cuentas-por-cobrar/', views.cuentas_por_cobrar, name='cuentas_por_cobrar'),
    path('<int:pk>/', views.detalle_venta, name='detalle_venta'),
    path('<int:pk>/agregar-articulos/', views.agregar_articulos, name='agregar_articulos'),
    path('<int:pk>/abonos/nuevo/', views.registrar_abono_view, name='registrar_abono'),
]
