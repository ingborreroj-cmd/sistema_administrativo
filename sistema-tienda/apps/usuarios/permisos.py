# apps/usuarios/permisos.py
from functools import wraps

from django.core.exceptions import PermissionDenied

def rol_requerido(*roles_permitidos):
    """
    Decorador para bloquear el acceso a vistas según el rol del usuario.
    Uso: @rol_requerido('ADMIN', 'ENCARGADO')
    """
    def decorador(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated and request.user.rol in roles_permitidos:
                return view_func(request, *args, **kwargs)
            else:
                raise PermissionDenied("No tienes permisos de seguridad para ver este módulo.")
        return _wrapped_view
    return decorador