from django.db import models
from django.contrib.auth.models import AbstractUser

class Sede(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.TextField(blank=True, null=True)
    activa = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class Usuario(AbstractUser):
    ROLES = (
        ('ADMIN', 'Administrador Global'),
        ('CAJERO', 'Cajero de Tienda'),
    )
    rol = models.CharField(max_length=15, choices=ROLES, default='CAJERO')
    
    # null=True y blank=True permite que el Admin Global no esté atado a una sola sede
    sede = models.ForeignKey(Sede, on_delete=models.SET_NULL, null=True, blank=True, related_name='empleados')

    def __str__(self):
        return f"{self.username} - {self.get_rol_display()}"

class RegistroAuditoria(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.CharField(max_length=255) # Ej: "Creó el usuario Juan" o "Eliminó el producto Café"
    modulo = models.CharField(max_length=50)  # Ej: "Usuarios", "Inventario", "Ventas"
    fecha = models.DateTimeField(auto_now_add=True)
    ip_origen = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        nombre_usuario = self.usuario.username if self.usuario else 'Sistema'
        return f"[{self.fecha.strftime('%Y-%m-%d %H:%M')}] {nombre_usuario} - {self.accion}"