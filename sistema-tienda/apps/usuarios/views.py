from datetime import datetime, time

import openpyxl
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import localdate, localtime, make_aware
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from .dashboard_summary import construir_resumen_operaciones
from .forms import EditarUsuarioForm, RegistroUsuarioForm, SedeForm
from .models import RegistroAuditoria, Sede, Usuario
from .permisos import rol_requerido


@login_required
def dashboard(request):
    resumen = construir_resumen_operaciones(
        request.user,
        sede_id=request.GET.get('sede'),
    )
    return render(request, 'usuarios/dashboard.html', {'resumen': resumen})

@login_required
@rol_requerido('ADMIN')
def lista_usuarios(request):
    # Traemos todos los usuarios ordenados por fecha de registro
    usuarios = Usuario.objects.all().order_by('-date_joined')
    return render(request, 'usuarios/lista_usuarios.html', {'usuarios': usuarios})


@login_required
@rol_requerido('ADMIN')
def crear_sede(request):
    if request.method == 'POST':
        form = SedeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                sede = form.save()
                RegistroAuditoria.objects.create(
                    usuario=request.user,
                    accion=f'Creó la sede: {sede.nombre}',
                    modulo='Usuarios',
                    ip_origen=request.META.get('REMOTE_ADDR'),
                )
            return redirect('lista_usuarios')
    else:
        form = SedeForm()

    return render(request, 'usuarios/crear_sede.html', {'form': form})

@login_required
@rol_requerido('ADMIN')
def lista_auditoria(request):
    # 1. Obtener los parámetros del formulario GET
    modulo = request.GET.get('modulo', '')
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    accion_exportar = request.GET.get('exportar', 'filtrar')

    # 2. Iniciar el QuerySet (Consulta base)
    registros = RegistroAuditoria.objects.all().order_by('-fecha')

    # 3. Aplicar Filtros si existen
    if modulo:
        registros = registros.filter(modulo=modulo)
    if fecha_inicio:
        try:
            f_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        except ValueError:
            messages.error(request, 'La fecha inicial no tiene un formato válido.')
        else:
            registros = registros.filter(fecha__gte=make_aware(f_inicio))
    if fecha_fin:
        try:
            fecha_final = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'La fecha final no tiene un formato válido.')
        else:
            f_fin = datetime.combine(fecha_final, time.max)
            registros = registros.filter(fecha__lte=make_aware(f_fin))

    # 4. Generar Reporte Excel
    if accion_exportar == 'excel':
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="auditoria.xlsx"'
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporte de Auditoría"
        
        # Encabezados
        encabezados = ['Fecha', 'Usuario', 'Rol', 'Módulo', 'Acción', 'IP Origen']
        ws.append(encabezados)
        
        # Datos
        for r in registros:
            ws.append([
                localtime(r.fecha).strftime('%Y-%m-%d %H:%M:%S'),
                r.usuario.username if r.usuario else 'Sistema',
                r.usuario.get_rol_display() if r.usuario else '-',
                r.modulo,
                r.accion,
                r.ip_origen or 'Local'
            ])
        wb.save(response)
        return response

    # 5. Generar Reporte PDF
    if accion_exportar == 'pdf':
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="auditoria.pdf"'
        
        # Usamos landscape (horizontal) porque las tablas de auditoría son anchas
        doc = SimpleDocTemplate(response, pagesize=landscape(letter))
        elementos = []
        
        estilos = getSampleStyleSheet()
        elementos.append(Paragraph("Reporte de Auditoría - Sistema Tienda", estilos['Title']))
        elementos.append(Paragraph(f'Registros generados el: {localdate():%Y-%m-%d}', estilos['Normal']))
        
        # Construir la estructura de la tabla
        datos_tabla = [['Fecha', 'Usuario', 'Módulo', 'Acción', 'Origen']]
        for r in registros:
            datos_tabla.append([
                localtime(r.fecha).strftime('%Y-%m-%d %H:%M'),
                r.usuario.username if r.usuario else 'Sistema',
                r.modulo,
                r.accion,
                r.ip_origen or 'Local'
            ])
            
        tabla = Table(datos_tabla)
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#272635')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#E8E9F3')),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#CECECE')),
        ]))
        
        elementos.append(tabla)
        doc.build(elementos)
        return response

    # 6. Si no es exportación, renderizamos la pantalla normal con la tabla filtrada
    # Limitamos a 100 resultados en pantalla para no colapsar la vista si hay miles
    return render(request, 'usuarios/lista_auditoria.html', {'registros': registros[:100]})

@login_required
@rol_requerido('ADMIN')
def crear_usuario(request):
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                nuevo_usuario = form.save()
                RegistroAuditoria.objects.create(
                    usuario=request.user,
                    accion=f'Registró al empleado: {nuevo_usuario.username} ({nuevo_usuario.get_rol_display()})',
                    modulo='Usuarios',
                    ip_origen=request.META.get('REMOTE_ADDR'),
                )
            return redirect('lista_usuarios')
    else:
        form = RegistroUsuarioForm()
        
    return render(request, 'usuarios/crear_usuario.html', {'form': form})

@login_required
@rol_requerido('ADMIN')
def editar_usuario(request, id):
    # Buscamos al usuario en la base de datos o devolvemos error 404 si no existe
    usuario_editar = get_object_or_404(Usuario, id=id)

    if request.method == 'POST':
        # Pasamos la instancia (instance) para que Django sepa que estamos actualizando, no creando
        form = EditarUsuarioForm(request.POST, instance=usuario_editar)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                estado = 'Activo' if usuario_editar.is_active else 'Suspendido'
                RegistroAuditoria.objects.create(
                    usuario=request.user,
                    accion=f'Modificó perfil de: {usuario_editar.username} | Rol: {usuario_editar.get_rol_display()} | Estado: {estado}',
                    modulo='Usuarios',
                    ip_origen=request.META.get('REMOTE_ADDR'),
                )
            return redirect('lista_usuarios')
    else:
        # Si es GET, cargamos el formulario con los datos actuales del usuario
        form = EditarUsuarioForm(instance=usuario_editar)
        
    return render(request, 'usuarios/editar_usuario.html', {'form': form, 'usuario_editar': usuario_editar})