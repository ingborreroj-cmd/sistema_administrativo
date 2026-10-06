# App de Usuarios y Seguridad

Esta aplicación gestiona las cuentas de acceso, roles de negocio, sedes y registros de auditoría del sistema POS. Es una app base: Inventario y Ventas dependen de sus modelos `Sede`, `Usuario` y `RegistroAuditoria`.

## Identificación

- App Django: `apps.usuarios`
- Configuración: `apps/usuarios/apps.py`
- Modelos: `apps/usuarios/models.py`
- URLs: `apps/usuarios/urls.py`
- Prefijo principal: raíz del sitio (`/`)
- Dependencias principales: Django Auth, Inventario y Ventas

Documentación de las demás apps: `apps/inventario/README.md` y `apps/ventas/README.md`.

## Funcionalidades actuales

- Inicio y cierre de sesión.
- Dashboard general con accesos a las áreas disponibles.
- Resumen de operaciones con facturación del día, número de facturas, deuda global, productos agotados, tendencia semanal y actividad reciente.
- Gestión de usuarios de negocio: listado, alta y edición.
- Asignación de usuario a sede.
- Alta de sedes desde Control de Usuarios.
- Consulta de auditoría con filtros y exportaciones Excel/PDF.
- Registro de acciones de los módulos en `RegistroAuditoria`.
- Administración de `Sede` y `Usuario` desde Django Admin.

## Modelos

### `Sede`

| Campo | Descripción |
|---|---|
| `nombre` | Nombre de la sede, máximo 100 caracteres |
| `direccion` | Dirección opcional |
| `activa` | Indica si la sede puede operar; por defecto `True` |

La sede se usa para limitar inventario, asignar cajeros y registrar ventas. En Inventario, eliminar una sede tiene efecto `CASCADE` sobre sus productos; las ventas y abonos la protegen mediante `PROTECT`.

### `Usuario`

Extiende `AbstractUser` de Django.

| Campo propio | Descripción |
|---|---|
| `rol` | Rol de negocio (`ADMIN` o `CAJERO`); por defecto `CAJERO` |
| `sede` | Sede asignada; opcional para administradores globales |

Django también mantiene `is_staff` e `is_superuser`. Estos indicadores **no son el rol de negocio**:

- `is_superuser`/`is_staff` controlan el acceso al panel `/admin/`.
- El acceso a las pantallas del sistema se determina principalmente con `rol`.
- Un usuario creado con `createsuperuser` recibe inicialmente el rol de negocio `CAJERO` si no se lo cambia después.
- El usuario superadministrador actual tiene `rol='ADMIN'`, además de los indicadores de Django.
- Actualmente no hay una matriz separada para “superadmin” y “admin normal”: ambos comparten los permisos de negocio `ADMIN` si tienen ese rol.

### `RegistroAuditoria`

Registra quién hizo una acción, su descripción, el módulo, la fecha automática y la IP opcional. El usuario puede ser nulo, por ejemplo para eventos del sistema; su representación muestra `Sistema` cuando no hay usuario.

## Permisos actuales

| Acción | `ADMIN` | `CAJERO` |
|---|---:|---:|
| Dashboard | Sí | Sí |
| Listado/alta/edición de usuarios | Sí | No |
| Crear sede | Sí | No |
| Consultar auditoría | Sí | No |
| Operar inventario | Todas las sedes activas | Solo sede asignada |
| Registrar ventas | Sede seleccionada | Solo sede asignada |
| Consultar/cobrar fiados pendientes | Sí | Sí, incluso si la deuda se originó en otra sede |
| Panel Django Admin | Depende de `is_staff` | Depende de `is_staff` |

El decorador `rol_requerido()` en `permisos.py` restringe vistas por `rol` y conserva metadata de la vista con `functools.wraps`.

## Rutas

| Método | Ruta | Nombre | Permiso/propósito |
|---|---|---|---|
| `GET` | `/login/` | `login` | Formulario de ingreso |
| `POST` | `/logout/` | `logout` | Cierre de sesión con CSRF |
| `GET` | `/` | `dashboard` | Panel de control para usuarios autenticados |
| `GET` | `/seguridad/usuarios/` | `lista_usuarios` | Solo `ADMIN` |
| `GET`, `POST` | `/seguridad/usuarios/crear/` | `crear_usuario` | Solo `ADMIN`; escribe usuario y auditoría en transacción |
| `GET`, `POST` | `/seguridad/usuarios/editar/<id>/` | `editar_usuario` | Solo `ADMIN`; actualiza perfil y auditoría en transacción |
| `GET`, `POST` | `/seguridad/sedes/crear/` | `crear_sede` | Solo `ADMIN`; registra sede y auditoría en transacción |
| `GET` | `/seguridad/auditoria/` | `lista_auditoria` | Solo `ADMIN`; permite filtros y exportación |

Las rutas principales se conectan desde `core/urls.py` al incluir `apps.usuarios.urls` en la raíz.

## Formularios y archivos

- `forms.py`: `SedeForm`, `RegistroUsuarioForm`, `EditarUsuarioForm`; las contraseñas nuevas se guardan mediante `set_password()`.
- `permisos.py`: decorador de autorización por roles.
- `admin.py`: registra sedes y usuarios y extiende el `UserAdmin` para mostrar rol/sede.
- `views.py`: dashboard, operaciones de seguridad y reportes de auditoría.
- `dashboard_summary.py`: consultas agregadas del panel; mantiene las métricas de operación fuera de la vista HTTP.
- `templates/usuarios/`: login, dashboard, alta/edición de usuarios, alta de sede y listado de auditoría/usuarios.

### Indicadores del dashboard

- **Facturado hoy** suma los subtotales de facturas abiertas durante el día local; incluye contado y fiado, por lo que representa facturación y no efectivo cobrado.
- **Operaciones hoy** cuenta facturas, no líneas de producto.
- **Deuda compartida** suma saldo pendiente de todos los fiados activos en todas las sedes, incluso si el resumen está filtrado por una sede.
- **Productos agotados** cuenta artículos cuyo stock es exactamente cero dentro del alcance visible; no se aplica un umbral arbitrario de stock bajo.
- **Ritmo de facturación** muestra importes diarios de los siete días recientes.
- **Actividad reciente** lista las últimas ocho facturas dentro del alcance de sede.

`ADMIN` puede seleccionar una sede activa o ver todas. `CAJERO` solo ve facturas y agotados de su sede activa. Sin una sede activa asignada, esas métricas se muestran vacías, pero las deudas siguen siendo globales por el contrato de cuentas por cobrar.

## Auditoría

Las acciones escritas en esta app y en los módulos relacionados comparten `RegistroAuditoria`. En los eventos de usuario/sede se almacena IP cuando la petición la proporciona. Las fechas inválidas en los filtros no deben detener la página; se informa el error y se conservan los demás resultados.

Las escrituras de crear/editar usuario y crear sede agrupan el cambio y el registro de auditoría con `transaction.atomic()` para evitar que solo se guarde una parte.

## Comandos

Ejecutar desde `sistema-tienda`, la carpeta que contiene `manage.py`:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py test apps.usuarios.tests
```

El usuario superadministrador de Django debe tener asignado el rol de negocio `ADMIN` si necesita acceder a Control de Usuarios, crear sedes o consultar la auditoría. Esto se puede comprobar/ajustar desde Django Admin en el registro del usuario.

## Pruebas

Las pruebas en `apps/usuarios/tests.py` cubren:

- Creación de sede por `ADMIN` y generación de auditoría.
- Bloqueo de alta de sede para `CAJERO`.
- Representación segura de auditorías con usuario nulo.
- Visualización de eventos de Ventas en la pantalla de auditoría.
- Tratamiento de fechas inválidas sin respuesta HTTP 500.
- Destinos del dashboard para los roles actuales.
- Alcance de métricas por sede, deuda compartida y filtro de sede para `ADMIN`.

## Límites conocidos y mejoras

- No hay separación funcional entre superadmin y admin normal; ambos son el rol `ADMIN`.
- El formulario normal de administración de usuarios puede asignar el rol `ADMIN`; si esto debe reservarse al superadmin, falta crear un permiso separado y filtrar opciones en formulario, vista, menú y pruebas.
- La gestión propia de sedes ofrece alta; listado/edición/desactivación continúan disponibles principalmente en Django Admin.
- Conviene definir una matriz formal de permisos antes de agregar nuevos roles, en vez de comprobar `rol` manualmente en múltiples módulos.
