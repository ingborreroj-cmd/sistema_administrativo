from xml.sax.saxutils import escape

import openpyxl
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _filas_reporte(ventas):
    filas = []
    for venta in ventas:
        total = venta.calcular_total()
        fecha_local = timezone.localtime(venta.fecha_apertura)
        filas.append([
            venta.pk,
            fecha_local.strftime('%Y-%m-%d %H:%M'),
            venta.cliente.nombre_completo,
            venta.cliente.cedula_o_rif,
            venta.sede.nombre,
            venta.tipo_pago,
            venta.estado,
            total,
            venta.calcular_saldo_deudor(),
        ])
    return filas


def exportar_excel(ventas, total_facturado):
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="reporte_ventas.xlsx"'
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Ventas'
    sheet.append(['Factura', 'Fecha', 'Cliente', 'Identificación', 'Sede', 'Pago', 'Estado', 'Total', 'Saldo'])
    for fila in _filas_reporte(ventas):
        sheet.append([*fila[:7], float(fila[7]), float(fila[8])])
    sheet.append([])
    sheet.append(['', '', '', '', '', '', 'Total facturado', float(total_facturado), ''])
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:I{sheet.max_row - 2}'
    workbook.save(response)
    return response


def exportar_pdf(ventas, total_facturado):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="reporte_ventas.pdf"'
    documento = SimpleDocTemplate(response, pagesize=landscape(letter), title='Reporte de ventas')
    estilos = getSampleStyleSheet()
    elementos = [Paragraph('Reporte de ventas', estilos['Title']), Spacer(1, 8)]
    elementos.append(Paragraph(f'Total facturado: ${total_facturado:.2f}', estilos['Heading2']))
    datos = [[
        'Factura', 'Fecha', 'Cliente', 'Identificación', 'Sede', 'Pago', 'Estado', 'Total', 'Saldo'
    ]]
    for fila in _filas_reporte(ventas):
        datos.append([
            str(fila[0]), fila[1], Paragraph(escape(str(fila[2])), estilos['BodyText']),
            str(fila[3]), Paragraph(escape(str(fila[4])), estilos['BodyText']),
            fila[5], fila[6], f'${fila[7]:.2f}', f'${fila[8]:.2f}',
        ])
    tabla = Table(datos, repeatRows=1, colWidths=[48, 76, 112, 75, 80, 55, 60, 55, 55])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#272635')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CECECE')),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F1F5F9')]),
    ]))
    elementos.append(tabla)
    documento.build(elementos)
    return response
