# App de Inventario

Módulo de inventario del sistema administrativo POS desarrollado con Django y PostgreSQL.

Permite gestionar productos por sede, controlar existencias, clasificar productos por categorías, consultar el inventario mediante filtros y mantener trazabilidad mediante auditoría.

Esta documentación corresponde exclusivamente a `apps/inventario`. Para los límites entre apps y permisos globales, consulta también `apps/usuarios/README.md` y `apps/ventas/README.md`.

Documentación central de permisos, sedes y auditoría: `apps/usuarios/README.md`. Reglas de venta y consumo de stock: `apps/ventas/README.md`.

## Ubicación

```text
apps/inventario/
├── admin.py
├── apps.py
├── forms.py
├── models.py
├── services.py
├── tests.py
├── urls.py
├── views.py
├── migrations/
│   ├── 0001_initial.py
│   └── __init__.py
└── README.md
```

## Funcionalidades

- Listado de productos de inventario.
- Creación de productos.
- Edición de productos.
- Eliminación protegida por stock.
- Creación de categorías desde el formulario de nuevo producto.
- Asociación de cada producto con una sede.
- Carga opcional de fotografías.
- Filtros por categoría, sede y rango de fechas de actualización.
- Auditoría de operaciones de inventario.
- Restricción de datos según la sede del usuario.
- Interfaz adaptable con Tailwind CSS y FontAwesome.

## Modelos

### `Categoria`

Representa una clasificación de productos.

| Campo | Tipo | Reglas |
|---|---|---|
| `nombre` | `CharField` | Obligatorio, máximo 50 caracteres y único |

Las categorías se ordenan alfabéticamente.

### `ProductoInventario`

Representa un producto registrado en una sede.

| Campo | Tipo | Reglas |
|---|---|---|
| `nombre` | `CharField` | Obligatorio, máximo 150 caracteres |
| `categoria` | `ForeignKey` | Relación protegida con `Categoria` |
| `cantidad` | `PositiveIntegerField` | No admite valores negativos |
| `precio` | `DecimalField` | Máximo 10 dígitos, 2 decimales, no negativo |
| `foto` | `ImageField` | Opcional, se guarda en `uploads/inventario_fotos/` |
| `fecha_actualizacion` | `DateTimeField` | Se actualiza automáticamente |
| `sede` | `ForeignKey` | Relación con `usuarios.Sede` |

La eliminación de una categoría está protegida mientras existan productos asociados. La eliminación de una sede elimina sus productos asociados debido a la regla `CASCADE` definida en el modelo.

## Reglas de negocio

### Stock

- La cantidad inicial es `0`.
- No se permiten cantidades negativas en el formulario ni en el modelo.
- Un producto con stock activo no puede eliminarse.
- La eliminación solo está permitida cuando `cantidad == 0`.
- Si se intenta eliminar un producto con stock, se muestra:

```text
No se puede eliminar un producto con stock activo
```

### Auditoría

Las operaciones de crear, editar y eliminar productos generan un registro en `RegistroAuditoria` con:

- Usuario que realizó la acción.
- Descripción de la acción.
- Módulo `Inventario`.
- Dirección IP cuando está disponible.
- Fecha automática del evento.

Las operaciones de escritura se ejecutan dentro de `transaction.atomic()` para evitar que el cambio de datos quede guardado sin su auditoría correspondiente.

La creación de categorías es independiente y actualmente no genera un evento de auditoría; la auditoría indicada arriba corresponde a las operaciones de productos.

## Roles y permisos

El sistema utiliza los roles definidos en `apps.usuarios.models.Usuario`.
El control de inventario usa el campo de negocio `rol`; `is_superuser` de Django es independiente y no sustituye la asignación de `rol='ADMIN'`.

### Administrador (`ADMIN`)

- Puede consultar productos de todas las sedes activas.
- Puede filtrar por sede.
- Puede crear, editar y eliminar productos de cualquier sede activa.
- Puede crear categorías desde el formulario de nuevo producto.
- Puede crear sedes desde Control de Usuarios.

### Cajero (`CAJERO`)

- Solo puede consultar productos de su sede asignada.
- Solo puede crear o editar productos de su sede activa.
- No puede consultar productos de otras sedes.
- No puede crear categorías.
- Debe tener una sede activa asignada para crear productos.

Un usuario sin sede activa no puede crear productos. En ese caso, el sistema muestra un mensaje y redirige al listado de inventario.

## Rutas

Las rutas están definidas en `apps/inventario/urls.py` y se incluyen desde `core/urls.py` con el prefijo `/inventario/`.

| Método | Ruta | Nombre | Descripción |
|---|---|---|---|
| `GET` | `/inventario/` | `inventario:lista_productos` | Lista y filtra productos |
| `GET`, `POST` | `/inventario/nuevo/` | `inventario:crear_producto` | Crea un producto |
| `GET`, `POST` | `/inventario/categorias/nueva/` | `inventario:crear_categoria` | Crea una categoría, solo `ADMIN` |
| `GET`, `POST` | `/inventario/<id>/editar/` | `inventario:editar_producto` | Edita un producto visible para el usuario |
| `GET`, `POST` | `/inventario/<id>/eliminar/` | `inventario:eliminar_producto` | Confirma y elimina un producto sin stock |

Todas las rutas requieren autenticación mediante `@login_required`.

## Filtros

El listado permite filtrar por:

- Categoría.
- Sede, disponible para administradores.
- Fecha de actualización inicial.
- Fecha de actualización final.

Los filtros se aplican sobre el queryset visible para el usuario. Por tanto, un usuario no administrador nunca puede usar un filtro para consultar productos de otra sede.

## Arquitectura

### `models.py`

Contiene las entidades `Categoria` y `ProductoInventario`, sus validaciones, relaciones e índices de consulta.

### `forms.py`

Contiene:

- `CategoriaForm` para crear categorías.
- `ProductoInventarioForm` para crear y editar productos.

Los formularios validan nombres, cantidades, precios y sedes disponibles.

### `services.py`

Centraliza la lógica de escritura:

- `crear_producto()`
- `actualizar_producto()`
- `eliminar_producto()`
- `StockActivoError`

Este diseño evita duplicar la lógica de transacciones y auditoría dentro de las vistas.

### `views.py`

Gestiona las peticiones HTTP, filtros, permisos de visibilidad, formularios, mensajes y redirecciones.

### `templates/inventario/`

Plantillas disponibles:

- `lista_productos.html`: listado y filtros.
- `form_producto.html`: alta y edición de productos.
- `form_categoria.html`: creación sencilla de categorías.
- `confirmar_eliminacion.html`: confirmación de eliminación.

Todas heredan de `base.html`.

## Configuración requerida

### Dependencias

El proyecto requiere las dependencias definidas en `requirements.txt`, especialmente:

- Django.
- `psycopg2-binary` para PostgreSQL.
- Pillow para `ImageField`.

Instalación:

```powershell
pip install -r requirements.txt
```

### PostgreSQL

El proyecto no utiliza SQLite. La conexión se configura mediante `.env` en la raíz de `sistema-tienda`:

```dotenv
DB_NAME=sistema_tienda
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432
```

La base de datos debe existir antes de aplicar las migraciones.

### Migraciones

Desde la carpeta que contiene `manage.py`:

```powershell
cd "C:\Users\DPain\Desktop\sistema_administrativo\sistema-tienda"
python manage.py migrate
```

Para comprobar si faltan migraciones:

```powershell
python manage.py makemigrations --check --dry-run
```

## Datos iniciales

Para poder crear productos se necesita al menos:

1. Una sede activa.
2. Una categoría.
3. Un usuario con sede asignada, si no se utiliza el rol `ADMIN`.

Las sedes pueden crearse desde Control de Usuarios mediante **Nueva Sede** o desde el panel administrativo de Django.

Las categorías pueden crearse directamente desde el enlace discreto **Nueva categoría** dentro de **Nuevo Producto**. También pueden administrarse desde Django Admin.

## Ejecución

Desde `sistema-tienda`:

```powershell
python manage.py runserver
```

URLs principales:

```text
http://127.0.0.1:8000/inventario/
http://127.0.0.1:8000/admin/
```

Es recomendable utilizar siempre el mismo host durante la sesión, por ejemplo `127.0.0.1`, para evitar problemas con cookies o tokens CSRF.

## Pruebas

Las pruebas del módulo están en `apps/inventario/tests.py`.

Ejecutar las pruebas de inventario:

```powershell
python manage.py test apps.inventario.tests
```

Las pruebas cubren:

- Bloqueo de eliminación cuando hay stock.
- Eliminación correcta cuando el stock es cero.
- Registro de auditoría.
- Visibilidad limitada por sede.
- Creación de categorías por administradores.
- Bloqueo de creación de categorías para usuarios no administradores.

Validación general:

```powershell
python manage.py check
python manage.py test apps.usuarios.tests apps.inventario.tests
```

## Consideraciones futuras

- Incorporar movimientos de inventario para registrar entradas y salidas.
- Evitar modificaciones directas de stock y centralizarlas en servicios de movimiento.
- Añadir paginación al listado de productos.
- Añadir edición y desactivación de categorías.
- Añadir gestión de sedes desde una pantalla propia con listado y edición.
- Configurar almacenamiento de medios para producción; en desarrollo `MEDIA_ROOT` apunta a `uploads/` y las imágenes se guardan en `uploads/inventario_fotos/`.
- Añadir permisos Django más granulares si se incorporan nuevos roles.
- Configurar almacenamiento externo para imágenes en producción.

## Estado de validación

La implementación actual fue validada con:

```text
System check identified no issues
Ran 5 tests
OK
```

## Relación con otras apps

- `usuarios`: aporta `Sede`, `Usuario` y `RegistroAuditoria`.
- `ventas`: consulta productos por sede, conserva el precio del producto en cada detalle y descuenta existencias mediante bloqueos transaccionales. No debe alterarse el stock desde las vistas de venta; la integración está centralizada en `apps/ventas/services.py`.

Para el mapa completo del sistema, cada app mantiene su propio documento: `apps/usuarios/README.md`, `apps/inventario/README.md` y `apps/ventas/README.md`.
