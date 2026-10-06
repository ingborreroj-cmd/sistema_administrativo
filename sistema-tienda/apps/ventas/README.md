# App de Ventas y Cuentas por Cobrar

Aplicación Django que registra facturas de contado y fiadas, mantiene detalles de venta, descuenta inventario y controla abonos a deudas. Los clientes son globales: una deuda originada en una sede se puede consultar y cobrar desde otra sede.

## Identificación

- App Django: `apps.ventas`
- Configuración: `apps/ventas/apps.py`
- Registro Django: `INSTALLED_APPS` de `core/settings.py`
- URLs: `apps/ventas/urls.py`
- Prefijo: `/ventas/`
- Integraciones: `apps.inventario`, `apps.usuarios` y PostgreSQL

Documentación relacionada: `apps/usuarios/README.md` describe roles/sedes/auditoría y `apps/inventario/README.md` describe el catálogo y el stock.

## Funcionalidades

- Crear ventas al contado o fiadas.
- Buscar clientes existentes por nombre o cédula/RIF.
- Registrar un cliente global cuando no existe.
- Agregar varios productos a una venta.
- Descontar stock automáticamente y rechazar stock insuficiente.
- Continuar agregando productos a una venta fiada pendiente, siempre desde la sede de origen.
- Consultar cuentas por cobrar globales y registrar abonos desde otra sede.
- Cambiar automáticamente la deuda a pagada cuando el saldo llega a cero.
- Consultar historial con búsqueda, fechas y filtro de sede para `ADMIN`.
- Exportar los resultados filtrados a Excel y PDF.
- Registrar ventas, artículos agregados y abonos en la auditoría compartida.

## Modelos y relaciones

### `Cliente`

El cliente no pertenece a una sede. Su número de cédula/RIF es único y sirve para buscarlo en todas las sucursales.

| Campo | Regla |
|---|---|
| `cedula_o_rif` | Obligatorio, máximo 20 caracteres, único |
| `nombre_completo` | Obligatorio, máximo 150 caracteres |
| `telefono` | Opcional, máximo 20 caracteres |
| `direccion` | Opcional |
| `fecha_registro` | Automática |

### `Venta`

Relaciona cliente, vendedor y sede. Guarda el tipo de pago (`CONTADO`/`FIADO`), estado (`PAGADA`/`PENDIENTE`) y fechas de apertura/actualización. El total se calcula a partir de sus líneas; el saldo resta los abonos.

Reglas de estado en base de datos:

- Una venta `CONTADO` debe estar `PAGADA`.
- Una venta `FIADO` puede estar `PENDIENTE` o `PAGADA`.

### `DetalleVenta`

Conecta una venta con un producto de inventario y conserva cantidad, precio unitario y subtotal de esa transacción. El precio se copia al registrar la venta para que un cambio posterior del precio del producto no modifique la factura histórica.

La cantidad debe ser positiva y el precio/subtotal no negativos; también hay restricciones PostgreSQL para estos valores.

### `Abono`

Registra pago parcial o final, fecha, método, cajero y sede receptora. El monto debe ser mayor que cero. La sede receptora usa `PROTECT`; la relación con venta usa `CASCADE`, aunque el Django Admin bloquea borrar ventas y abonos para preservar la trazabilidad.

## Reglas transaccionales

La lógica de escritura reside en `services.py` y usa `transaction.atomic()`:

1. Se valida que el tipo de pago y la sede sean válidos y que la sede esté activa.
2. Se valida autorización del vendedor para operar en la sede.
3. Se bloquean las filas de productos con `select_for_update()` en orden estable.
4. Se comprueba que todos los productos pertenezcan a la sede y tengan stock suficiente.
5. Se crea venta, detalle, actualización de stock y auditoría dentro de la misma transacción.
6. Si falla cualquier validación, PostgreSQL revierte la operación completa, incluido un cliente recién creado.

Para fiados pendientes, agregar artículos descuenta stock y suma nuevas líneas a la misma venta. Los abonos bloquean la venta, no pueden exceder su saldo y actualizan el estado a `PAGADA` cuando el saldo queda en cero.

### Servicios

- `crear_venta(...)`
- `agregar_articulos_fiados(...)`
- `registrar_abono(...)`
- `VentaError`: error de negocio esperado para validaciones de operación.

La autorización está dentro del servicio además de las validaciones del formulario/vista, de manera que invocaciones desde otro punto no puedan saltarse el límite de sede.

## Permisos actuales

- `ADMIN`: puede operar en sedes activas y filtrar reportes por sede.
- `CAJERO`: puede registrar ventas únicamente en su sede activa.
- Un cajero solo agrega productos a una venta fiada pendiente de su sede.
- Las deudas fiadas pendientes son globales; un cajero puede consultarlas y registrar el abono en su propia sede.
- Los servicios vuelven a verificar la sede; el cliente no puede cambiar una sede restringida alterando el formulario.
- Django Admin permite consultar registros financieros, pero no crear, editar ni borrar ventas, detalles o abonos fuera del servicio transaccional.

El rol de negocio `ADMIN` no es equivalente a `is_superuser`: véase `apps/usuarios/README.md`.

## Rutas

| Método | Ruta | Nombre | Descripción |
|---|---|---|---|
| `GET` | `/ventas/` | `ventas:historial` | Historial filtrable; exporta por parámetros `exportar=excel` o `exportar=pdf` |
| `GET`, `POST` | `/ventas/nueva/` | `ventas:nueva_venta` | Formulario y registro de venta |
| `GET` | `/ventas/clientes/buscar/?q=...` | `ventas:buscar_clientes` | JSON de hasta 10 clientes encontrados |
| `GET` | `/ventas/cuentas-por-cobrar/` | `ventas:cuentas_por_cobrar` | Deudas fiadas pendientes globales |
| `GET` | `/ventas/<id>/` | `ventas:detalle_venta` | Factura, líneas y abonos |
| `POST` | `/ventas/<id>/agregar-articulos/` | `ventas:agregar_articulos` | Agrega líneas a fiado pendiente |
| `GET`, `POST` | `/ventas/<id>/abonos/nuevo/` | `ventas:registrar_abono` | Registra un abono |

Las vistas requieren autenticación. El buscador recibe `q` por GET, exige dos caracteres para consultar y limita la respuesta a 10 coincidencias.

## Arquitectura por archivo

- `models.py`: clientes, ventas, líneas, abonos, agregados e invariantes.
- `forms.py`: validación de datos de venta y abono y limitación de sedes seleccionables.
- `services.py`: transacciones, bloqueo de stock/saldo, autorización y auditoría.
- `selectors.py`: filtros de búsqueda, fechas y sede; agregado del total facturado.
- `reports.py`: generación Excel/PDF para los resultados filtrados.
- `views.py`: orquestación HTTP, mensajes, renderizado, búsqueda JSON y paginación.
- `admin.py`: consulta de registros financieros en modo de solo lectura.
- `tests.py`: reglas de servicio, vistas, reportes, permisos y Admin.
- `templates/ventas/`: alta de venta, historial, cuenta por cobrar, detalle y abono.

## Auditoría

Los eventos usan `apps.usuarios.models.RegistroAuditoria` con `modulo='Ventas'`. Se registran ventas, artículos agregados al fiado y abonos. La IP se agrega cuando se dispone de la petición HTTP. Auditoría y movimiento monetario/de inventario comparten transacción; un fallo de auditoría revierte la operación.

## Migraciones y ejecución

La app depende de las migraciones iniciales de usuarios e inventario. Migraciones propias actuales:

- `0001_initial`: tablas Cliente, Venta, DetalleVenta y Abono e índices.
- `0002_abono_ventas_abono_monto_positivo_and_more`: constraints para montos/cantidades y consistencia tipo/estado.

Ejecutar desde la carpeta `sistema-tienda` donde está `manage.py`:

```powershell
python manage.py migrate
python manage.py check
python manage.py test apps.ventas.tests
```

URLs de uso local:

```text
http://127.0.0.1:8000/ventas/
http://127.0.0.1:8000/ventas/nueva/
http://127.0.0.1:8000/ventas/cuentas-por-cobrar/
```

La app está configurada para PostgreSQL a través de las variables de entorno del proyecto; no usa SQLite.
El huso horario del proyecto es `America/Caracas` con `USE_TZ=True`: la base conserva instantes conscientes de zona y las pantallas/reportes los presentan en hora venezolana. Los reportes convierten explícitamente las fechas a la zona activa antes de formatearlas.

## Cobertura actual

Las pruebas cubren:

- Contado: factura, total, stock y auditoría.
- Stock insuficiente y rollback completo.
- Restricción de producto a sede de venta.
- Fiado: agregar artículos a la misma deuda.
- Abono entre sedes, rechazo de sobrepago y cierre de saldo.
- Aislamiento por sede de servicios.
- Búsqueda de clientes y renderizado de páginas.
- Exportaciones Excel/PDF; Excel se verifica leyendo el archivo y comprobando filtros y totales.
- Paginación y cálculo sin consultas por fila cuando las relaciones se precargan.
- Inmutabilidad financiera desde Django Admin.
- Integración de auditoría legacy.

Ejecutar la regresión completa:

```powershell
python manage.py test apps.usuarios.tests apps.inventario.tests apps.ventas.tests
```

## Límites conocidos

- No hay anulación, devolución ni edición/eliminación de facturas; es intencional para proteger la trazabilidad, pero una política de reversos deberá diseñarse antes de producción.
- Las exportaciones generan el archivo durante la petición y materializan los resultados filtrados; informes grandes deberían pasar a tareas asíncronas.
- Los totales se derivan de detalles y abonos; no se almacena un snapshot agregado separado.
- Se recomienda validar concurrencia con carga simultánea en PostgreSQL antes del despliegue, aunque el stock y el saldo ya usan bloqueos transaccionales.
