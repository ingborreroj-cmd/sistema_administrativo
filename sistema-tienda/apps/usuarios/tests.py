from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.inventario.models import Categoria, ProductoInventario
from apps.ventas.models import Venta
from apps.ventas.services import crear_venta

from .models import RegistroAuditoria, Sede, Usuario


class CrearSedeTests(TestCase):
	def setUp(self):
		self.admin = Usuario.objects.create_user(
			username='admin_sedes',
			password='una-clave-segura',
			rol='ADMIN',
		)
		self.cajero = Usuario.objects.create_user(
			username='cajero_sedes',
			password='una-clave-segura',
			rol='CAJERO',
		)

	def test_admin_puede_crear_sede_y_se_audita(self):
		self.client.force_login(self.admin)
		response = self.client.post(reverse('crear_sede'), {
			'nombre': 'Sede Principal',
			'direccion': 'Calle 1',
			'activa': 'on',
		})

		self.assertRedirects(response, reverse('lista_usuarios'))
		self.assertTrue(self.admin.registroauditoria_set.filter(
			modulo='Usuarios',
			accion='Creó la sede: Sede Principal',
		).exists())

	def test_usuario_no_admin_no_puede_crear_sede(self):
		self.client.force_login(self.cajero)
		response = self.client.get(reverse('crear_sede'))

		self.assertEqual(response.status_code, 403)

	def test_auditoria_sin_usuario_se_muestra_sin_error(self):
		registro = RegistroAuditoria.objects.create(
			usuario=None,
			accion='Evento del sistema',
			modulo='Sistema',
		)

		self.assertIn('Sistema - Evento del sistema', str(registro))

	def test_auditoria_legacy_muestra_eventos_de_ventas(self):
		RegistroAuditoria.objects.create(
			usuario=self.admin,
			accion='Registró venta al CONTADO por 12.50',
			modulo='Ventas',
		)
		self.client.force_login(self.admin)

		response = self.client.get(reverse('lista_auditoria'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Ventas')
		self.assertContains(response, 'Registró venta al CONTADO por 12.50')

	def test_fechas_invalidas_en_auditoria_no_producen_error_500(self):
		self.client.force_login(self.admin)

		response = self.client.get(reverse('lista_auditoria'), {
			'fecha_inicio': 'no-es-fecha',
			'fecha_fin': 'tampoco-es-fecha',
		})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'formato válido')

	def test_dashboard_tiene_accesos_reales_para_roles_actuales(self):
		rutas = [
			reverse('ventas:nueva_venta'),
			reverse('ventas:cuentas_por_cobrar'),
			reverse('inventario:lista_productos'),
			reverse('ventas:historial'),
		]

		for usuario in (self.admin, self.cajero):
			with self.subTest(rol=usuario.rol):
				self.client.force_login(usuario)
				response = self.client.get(reverse('dashboard'))
				self.assertEqual(response.status_code, 200)
				for ruta in rutas:
					self.assertContains(response, f'href="{ruta}"')
				self.assertNotContains(response, 'href="#"')


class ResumenOperacionesTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.sede_norte = Sede.objects.create(nombre='Sede Norte')
		cls.sede_sur = Sede.objects.create(nombre='Sede Sur')
		cls.categoria = Categoria.objects.create(nombre='Bebidas Dashboard')
		cls.producto_norte = ProductoInventario.objects.create(
			nombre='Agua Norte', categoria=cls.categoria, cantidad=8,
			precio=Decimal('4.00'), sede=cls.sede_norte,
		)
		cls.producto_sur = ProductoInventario.objects.create(
			nombre='Jugo Sur', categoria=cls.categoria, cantidad=8,
			precio=Decimal('7.00'), sede=cls.sede_sur,
		)
		cls.agotado_norte = ProductoInventario.objects.create(
			nombre='Sin stock Norte', categoria=cls.categoria, cantidad=0,
			precio=Decimal('2.00'), sede=cls.sede_norte,
		)
		cls.cajero_norte = Usuario.objects.create_user(
			username='dashboard_norte', password='segura-123',
			rol='CAJERO', sede=cls.sede_norte,
		)
		cls.cajero_sur = Usuario.objects.create_user(
			username='dashboard_sur', password='segura-123',
			rol='CAJERO', sede=cls.sede_sur,
		)
		cls.admin = Usuario.objects.create_user(
			username='dashboard_admin', password='segura-123', rol='ADMIN',
		)
		crear_venta(
			datos_cliente={'cedula_o_rif': 'DASH-1', 'nombre_completo': 'Cliente Norte'},
			vendedor=cls.cajero_norte,
			sede=cls.sede_norte,
			tipo_pago=Venta.CONTADO,
			articulos=[{'producto_id': cls.producto_norte.pk, 'cantidad': 2}],
		)
		crear_venta(
			datos_cliente={'cedula_o_rif': 'DASH-2', 'nombre_completo': 'Cliente Sur'},
			vendedor=cls.cajero_sur,
			sede=cls.sede_sur,
			tipo_pago=Venta.FIADO,
			articulos=[{'producto_id': cls.producto_sur.pk, 'cantidad': 2}],
		)

	def test_cajero_ve_su_sede_pero_la_deuda_es_global(self):
		self.client.force_login(self.cajero_norte)
		response = self.client.get(reverse('dashboard'))
		resumen = response.context['resumen']

		self.assertEqual(resumen['ventas_hoy'], 1)
		self.assertEqual(resumen['facturado_hoy'], Decimal('8.00'))
		self.assertEqual(resumen['productos_agotados_total'], 1)
		self.assertEqual(resumen['saldo_global'], Decimal('14.00'))
		self.assertEqual(len(resumen['actividad_semanal']), 7)
		self.assertEqual([venta.cliente.nombre_completo for venta in resumen['ventas_recientes']], ['Cliente Norte'])

	def test_admin_puede_filtrar_metricas_por_sede(self):
		self.client.force_login(self.admin)
		response = self.client.get(reverse('dashboard'), {'sede': self.sede_sur.pk})
		resumen = response.context['resumen']

		self.assertEqual(resumen['alcance'], 'Sede Sur')
		self.assertEqual(resumen['ventas_hoy'], 1)
		self.assertEqual(resumen['facturado_hoy'], Decimal('14.00'))
		self.assertEqual(resumen['productos_agotados_total'], 0)
		self.assertEqual([venta.cliente.nombre_completo for venta in resumen['ventas_recientes']], ['Cliente Sur'])
