import json
from datetime import datetime, timezone as datetime_timezone
from io import BytesIO
from decimal import Decimal

from django.contrib import admin
from django.conf import settings
from django.test import RequestFactory
from django.utils import timezone
from openpyxl import load_workbook
from django.test import TestCase
from django.urls import reverse

from apps.inventario.models import Categoria, ProductoInventario
from apps.usuarios.models import RegistroAuditoria, Sede, Usuario

from apps.ventas.models import Abono, Cliente, DetalleVenta, Venta, VentaEvento
from apps.ventas.admin import AbonoAdmin, AbonoInline, DetalleVentaInline, VentaAdmin
from apps.ventas.services import VentaError, agregar_articulos_fiados, anular_venta, crear_venta, registrar_abono, registrar_devolucion
from apps.ventas.selectors import obtener_total_facturado


class VentasServicesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sede = Sede.objects.create(nombre='Sede Uno', activa=True)
        cls.sede_dos = Sede.objects.create(nombre='Sede Dos', activa=True)
        cls.categoria = Categoria.objects.create(nombre='Abarrotes')
        cls.producto = ProductoInventario.objects.create(
            nombre='Arroz', categoria=cls.categoria, cantidad=10,
            precio=Decimal('2.50'), sede=cls.sede,
        )
        cls.producto_otra_sede = ProductoInventario.objects.create(
            nombre='Leche', categoria=cls.categoria, cantidad=5,
            precio=Decimal('3.00'), sede=cls.sede_dos,
        )
        cls.cajero = Usuario.objects.create_user(
            username='cajero_ventas', password='segura-123', rol='CAJERO', sede=cls.sede,
        )
        cls.cajero_dos = Usuario.objects.create_user(
            username='cajero_ventas_dos', password='segura-123', rol='CAJERO', sede=cls.sede_dos,
        )

    def crear_venta_fiada(self, cantidad=2):
        return crear_venta(
            datos_cliente={
                'cedula_o_rif': 'V-12345',
                'nombre_completo': 'Cliente Prueba',
            },
            vendedor=self.cajero,
            sede=self.sede,
            tipo_pago=Venta.FIADO,
            articulos=[{'producto_id': self.producto.pk, 'cantidad': cantidad}],
        )

    def test_venta_contado_descuenta_stock_y_audita(self):
        venta = crear_venta(
            datos_cliente={
                'cedula_o_rif': 'V-54321',
                'nombre_completo': 'Cliente Contado',
            },
            vendedor=self.cajero,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            articulos=[{'producto_id': self.producto.pk, 'cantidad': 3}],
        )

        self.producto.refresh_from_db()
        self.assertEqual(venta.estado, Venta.PAGADA)
        self.assertEqual(venta.calcular_total(), Decimal('7.50'))
        self.assertEqual(self.producto.cantidad, 7)
        self.assertTrue(RegistroAuditoria.objects.filter(modulo='Ventas', accion__startswith='Registró venta').exists())

    def test_stock_insuficiente_no_crea_venta_ni_descuenta(self):
        with self.assertRaises(VentaError):
            self.crear_venta_fiada(cantidad=11)

        self.producto.refresh_from_db()
        self.assertEqual(self.producto.cantidad, 10)
        self.assertFalse(Venta.objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_venta_fiada_acepta_articulos_adicionales_y_abonos_cierra_saldo(self):
        venta = self.crear_venta_fiada(cantidad=2)
        agregar_articulos_fiados(
            venta_id=venta.pk,
            articulos=[{'producto_id': self.producto.pk, 'cantidad': 1}],
            usuario=self.cajero,
        )
        abono = registrar_abono(
            venta_id=venta.pk,
            monto='7.50',
            metodo_pago=Abono.PUNTO_DE_VENTA,
            cajero=self.cajero_dos,
            sede_donde_paga=self.sede_dos,
        )

        venta.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(abono.venta_id, venta.pk)
        self.assertEqual(venta.estado, Venta.PAGADA)
        self.assertEqual(venta.calcular_saldo_deudor(), Decimal('0.00'))
        self.assertEqual(self.producto.cantidad, 7)
        self.assertEqual(DetalleVenta.objects.filter(venta=venta).count(), 2)

    def test_abono_no_puede_superar_saldo(self):
        venta = self.crear_venta_fiada()

        with self.assertRaises(VentaError):
            registrar_abono(
                venta_id=venta.pk,
                monto='99.00',
                metodo_pago=Abono.PAGO_MOVIL,
                cajero=self.cajero,
                sede_donde_paga=self.sede,
            )

        self.assertFalse(Abono.objects.filter(venta=venta).exists())

    def test_anular_venta_restaura_stock_y_estado(self):
        venta = self.crear_venta_fiada(cantidad=2)

        self.assertTrue(self.producto.cantidad >= 8)
        self.producto.refresh_from_db()

    def test_registrar_devolucion_restaura_stock(self):
        venta = self.crear_venta_fiada(cantidad=2)
        detalle = venta.detalles.first()

        self.assertIsNotNone(detalle)
        self.assertEqual(venta.detalles.count(), 1)

    def test_anular_venta_crea_registro_de_cancelacion(self):
        venta = crear_venta(
            datos_cliente={
                'cedula_o_rif': 'V-66000',
                'nombre_completo': 'Cliente Cancelado',
            },
            vendedor=self.cajero,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            articulos=[{'producto_id': self.producto.pk, 'cantidad': 2}],
        )

        anular_venta(venta_id=venta.pk, usuario=self.cajero, motivo='Cambio de pedido')

        self.assertTrue(
            VentaEvento.objects.filter(
                venta=venta,
                tipo_evento=VentaEvento.CANCELACION,
                usuario=self.cajero,
                motivo='Cambio de pedido',
            ).exists()
        )

    def test_registrar_devolucion_crea_registro_devolucion(self):
        venta = self.crear_venta_fiada(cantidad=2)
        detalle = venta.detalles.first()

        devolucion = registrar_devolucion(
            venta_id=venta.pk,
            producto_id=detalle.producto_id,
            cantidad=1,
            cajero=self.cajero,
            motivo='Defecto de empaque',
        )

        self.assertTrue(
            VentaEvento.objects.filter(
                venta=venta,
                tipo_evento=VentaEvento.DEVOLUCION,
                producto=detalle.producto,
                cantidad=1,
                usuario=self.cajero,
                motivo='Defecto de empaque',
            ).exists()
        )
        self.assertEqual(devolucion.cantidad, 1)

    def test_no_se_vende_producto_de_otra_sede(self):
        with self.assertRaises(VentaError):
            crear_venta(
                datos_cliente={'cedula_o_rif': 'V-8899', 'nombre_completo': 'Cliente Otra Sede'},
                vendedor=self.cajero,
                sede=self.sede,
                tipo_pago=Venta.CONTADO,
                articulos=[{'producto_id': self.producto_otra_sede.pk, 'cantidad': 1}],
            )

        self.assertFalse(Venta.objects.exists())

    def test_servicio_impide_que_cajero_registre_venta_en_otra_sede(self):
        with self.assertRaises(VentaError):
            crear_venta(
                datos_cliente={'cedula_o_rif': 'V-7788', 'nombre_completo': 'Cliente Sede Dos'},
                vendedor=self.cajero,
                sede=self.sede_dos,
                tipo_pago=Venta.CONTADO,
                articulos=[{'producto_id': self.producto_otra_sede.pk, 'cantidad': 1}],
            )

        self.assertFalse(Venta.objects.exists())

    def test_calculos_usan_prefetch_sin_consultas_por_registro(self):
        venta = self.crear_venta_fiada()
        venta_con_relaciones = Venta.objects.prefetch_related('detalles', 'abonos').get(pk=venta.pk)

        with self.assertNumQueries(0):
            self.assertEqual(venta_con_relaciones.calcular_total(), Decimal('5.00'))
            self.assertEqual(venta_con_relaciones.calcular_saldo_deudor(), Decimal('5.00'))


class VentasViewsTests(TestCase):
    def setUp(self):
        self.sede = Sede.objects.create(nombre='Sede Web')
        self.usuario = Usuario.objects.create_user(
            username='usuario_web', password='segura-123', rol='CAJERO', sede=self.sede,
        )
        self.client.force_login(self.usuario)

    def test_busqueda_clientes_responde_json(self):
        Cliente.objects.create(cedula_o_rif='J-1020', nombre_completo='Cliente Web')

        response = self.client.get(reverse('ventas:buscar_clientes'), {'q': 'Cliente'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['clientes'][0]['identificacion'], 'J-1020')

    def test_vistas_de_ventas_y_deudas_renderizan(self):
        categoria = Categoria.objects.create(nombre='Categoría Web')
        ProductoInventario.objects.create(
            nombre='Producto Web', categoria=categoria, cantidad=4,
            precio=Decimal('1.25'), sede=self.sede,
        )

        nueva = self.client.get(reverse('ventas:nueva_venta'))
        historial = self.client.get(reverse('ventas:historial'))
        deudas = self.client.get(reverse('ventas:cuentas_por_cobrar'))

        self.assertEqual(nueva.status_code, 200)
        self.assertContains(nueva, 'Nueva venta')
        self.assertEqual(historial.status_code, 200)
        self.assertContains(historial, 'Historial de ventas')
        self.assertEqual(deudas.status_code, 200)
        self.assertContains(deudas, 'Cuentas por cobrar')

    def test_exportaciones_responden_en_formato_correcto(self):
        response_excel = self.client.get(reverse('ventas:historial'), {'exportar': 'excel'})
        response_pdf = self.client.get(reverse('ventas:historial'), {'exportar': 'pdf'})

        self.assertEqual(response_excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(response_pdf['Content-Type'], 'application/pdf')

    def test_detalle_venta_fiado_renderiza_productos_json_serializables(self):
        categoria = Categoria.objects.create(nombre='Fiado JSON')
        producto = ProductoInventario.objects.create(
            nombre='Galletas', categoria=categoria, cantidad=10,
            precio=Decimal('1.50'), sede=self.sede,
        )
        venta = crear_venta(
            datos_cliente={'cedula_o_rif': 'V-40404', 'nombre_completo': 'Cliente JSON'},
            vendedor=self.usuario,
            sede=self.sede,
            tipo_pago=Venta.FIADO,
            articulos=[{'producto_id': producto.pk, 'cantidad': 2}],
        )

        response = self.client.get(reverse('ventas:detalle_venta', args=[venta.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agregar artículos al fiado')
        self.assertContains(response, 'pending-products-data')

    def test_excel_respeta_filtros_y_totales(self):
        categoria = Categoria.objects.create(nombre='Reporte Filtrado')
        producto = ProductoInventario.objects.create(
            nombre='Artículo Reporte', categoria=categoria, cantidad=5,
            precio=Decimal('2.75'), sede=self.sede,
        )
        crear_venta(
            datos_cliente={'cedula_o_rif': 'V-12121', 'nombre_completo': 'Cliente Incluido'},
            vendedor=self.usuario,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            articulos=[{'producto_id': producto.pk, 'cantidad': 2}],
        )
        crear_venta(
            datos_cliente={'cedula_o_rif': 'V-34343', 'nombre_completo': 'Cliente Excluido'},
            vendedor=self.usuario,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            articulos=[{'producto_id': producto.pk, 'cantidad': 1}],
        )

        response = self.client.get(reverse('ventas:historial'), {
            'q': 'Cliente Incluido',
            'exportar': 'excel',
        })
        sheet = load_workbook(BytesIO(response.content), read_only=True).active
        filas = list(sheet.values)

        self.assertEqual(filas[1][2], 'Cliente Incluido')
        self.assertEqual(filas[1][7], 5.5)
        self.assertEqual(filas[-1][7], 5.5)
        self.assertNotIn('Cliente Excluido', [fila[2] for fila in filas if len(fila) > 2])


    def test_formulario_registra_venta_y_descuenta_inventario(self):
        categoria = Categoria.objects.create(nombre='Venta Integrada')
        producto = ProductoInventario.objects.create(
            nombre='Jabón', categoria=categoria, cantidad=4,
            precio=Decimal('3.25'), sede=self.sede,
        )

        response = self.client.post(reverse('ventas:nueva_venta'), {
            'cliente_id': '',
            'cedula_o_rif': 'V-90909',
            'nombre_completo': 'Cliente Integrado',
            'telefono': '',
            'direccion': '',
            'tipo_pago': Venta.CONTADO,
            'sede': self.sede.pk,
            'articulos': json.dumps([{'producto_id': producto.pk, 'cantidad': 2}]),
        })

        producto.refresh_from_db()
        venta = Venta.objects.get(cliente__cedula_o_rif='V-90909')
        self.assertRedirects(response, reverse('ventas:detalle_venta', args=[venta.pk]))
        self.assertEqual(producto.cantidad, 2)
        self.assertEqual(venta.calcular_total(), Decimal('6.50'))

    def test_cajero_consulta_deuda_global_y_la_cobra_en_su_sede(self):
        sede_origen = Sede.objects.create(nombre='Sede Origen')
        vendedor_origen = Usuario.objects.create_user(
            username='vendedor_origen', password='segura-123', rol='CAJERO', sede=sede_origen,
        )
        categoria = Categoria.objects.create(nombre='Deuda Global')
        producto = ProductoInventario.objects.create(
            nombre='Producto Fiado', categoria=categoria, cantidad=3,
            precio=Decimal('5.00'), sede=sede_origen,
        )
        venta = crear_venta(
            datos_cliente={'cedula_o_rif': 'V-45454', 'nombre_completo': 'Cliente Global'},
            vendedor=vendedor_origen,
            sede=sede_origen,
            tipo_pago=Venta.FIADO,
            articulos=[{'producto_id': producto.pk, 'cantidad': 2}],
        )

        deudas = self.client.get(reverse('ventas:cuentas_por_cobrar'))
        detalle = self.client.get(reverse('ventas:detalle_venta', args=[venta.pk]))
        respuesta_abono = self.client.post(reverse('ventas:registrar_abono', args=[venta.pk]), {
            'monto': '4.00',
            'metodo_pago': Abono.PAGO_MOVIL,
            'sede_donde_paga': self.sede.pk,
        })

        venta.refresh_from_db()
        self.assertContains(deudas, 'Cliente Global')
        self.assertEqual(detalle.status_code, 200)
        self.assertRedirects(respuesta_abono, reverse('ventas:detalle_venta', args=[venta.pk]))
        self.assertEqual(venta.calcular_saldo_deudor(), Decimal('6.00'))
        self.assertEqual(venta.estado, Venta.PENDIENTE)

    def test_total_facturado_respeta_filtro_de_sede_y_periodo(self):
        categoria = Categoria.objects.create(nombre='Total Web')
        producto = ProductoInventario.objects.create(
            nombre='Total Producto', categoria=categoria, cantidad=5,
            precio=Decimal('4.00'), sede=self.sede,
        )
        venta = crear_venta(
            datos_cliente={'cedula_o_rif': 'J-33221', 'nombre_completo': 'Total Cliente'},
            vendedor=self.usuario,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            articulos=[{'producto_id': producto.pk, 'cantidad': 2}],
        )
        queryset = Venta.objects.filter(pk=venta.pk)

        self.assertEqual(obtener_total_facturado(queryset), Decimal('8.00'))

    def test_historial_pagina_resultados(self):
        cliente = Cliente.objects.create(cedula_o_rif='V-10000', nombre_completo='Cliente Paginado')
        Venta.objects.bulk_create([
            Venta(
                cliente=cliente,
                vendedor=self.usuario,
                sede=self.sede,
                tipo_pago=Venta.CONTADO,
                estado=Venta.PAGADA,
            )
            for _ in range(51)
        ])

        response = self.client.get(reverse('ventas:historial'), {'page': 2})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Página 2 de 2')

    def test_facturas_y_reportes_usan_hora_de_caracas(self):
        cliente = Cliente.objects.create(cedula_o_rif='V-70707', nombre_completo='Cliente Hora')
        venta = Venta.objects.create(
            cliente=cliente,
            vendedor=self.usuario,
            sede=self.sede,
            tipo_pago=Venta.CONTADO,
            estado=Venta.PAGADA,
        )
        Venta.objects.filter(pk=venta.pk).update(
            fecha_apertura=datetime(2026, 9, 30, 2, 30, tzinfo=datetime_timezone.utc),
        )

        response = self.client.get(reverse('ventas:historial'), {'exportar': 'excel'})
        sheet = load_workbook(BytesIO(response.content), read_only=True).active
        filas = list(sheet.values)

        self.assertEqual(settings.TIME_ZONE, 'America/Caracas')
        self.assertEqual(filas[1][1], '2026-09-29 22:30')
        response_historial = self.client.get(reverse('ventas:historial'), {
            'desde': '2026-09-29',
            'hasta': '2026-09-29',
        })
        self.assertContains(response_historial, 'Cliente Hora')


class VentasAdminTests(TestCase):
    def test_registros_financieros_son_solo_lectura_en_admin(self):
        request = RequestFactory().get('/admin/')
        venta_admin = VentaAdmin(Venta, admin.site)
        abono_admin = AbonoAdmin(Abono, admin.site)
        detalle_inline = DetalleVentaInline(Venta, admin.site)
        abono_inline = AbonoInline(Venta, admin.site)

        self.assertFalse(venta_admin.has_add_permission(request))
        self.assertFalse(venta_admin.has_delete_permission(request))
        self.assertFalse(abono_admin.has_add_permission(request))
        self.assertFalse(abono_admin.has_delete_permission(request))
        self.assertFalse(detalle_inline.has_add_permission(request))
        self.assertFalse(detalle_inline.has_delete_permission(request))
        self.assertFalse(abono_inline.has_add_permission(request))
        self.assertFalse(abono_inline.has_delete_permission(request))
