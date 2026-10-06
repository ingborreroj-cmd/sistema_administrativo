from decimal import Decimal

from django import forms

from apps.usuarios.models import Sede

from .models import Venta


INPUT_CLASS = 'mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-cyan-600 focus:outline-none focus:ring-2 focus:ring-cyan-100'


class VentaForm(forms.Form):
    cliente_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    cedula_o_rif = forms.CharField(max_length=20, required=False, label='Cédula o RIF')
    nombre_completo = forms.CharField(max_length=150, required=False, label='Nombre completo')
    telefono = forms.CharField(max_length=20, required=False, label='Teléfono')
    direccion = forms.CharField(required=False, label='Dirección', widget=forms.Textarea(attrs={'rows': 2}))
    tipo_pago = forms.ChoiceField(choices=Venta.TIPOS_PAGO, label='Tipo de pago')
    sede = forms.ModelChoiceField(queryset=Sede.objects.none(), required=True, label='Sede')

    def __init__(self, *args, sedes=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = INPUT_CLASS
        self.fields['sede'].queryset = sedes if sedes is not None else Sede.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('cliente_id') and not (
            cleaned_data.get('cedula_o_rif') and cleaned_data.get('nombre_completo')
        ):
            raise forms.ValidationError('Busca un cliente o completa su identificación y nombre.')
        return cleaned_data


class AbonoForm(forms.Form):
    monto = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=12,
        decimal_places=2,
        label='Monto del abono',
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )
    metodo_pago = forms.CharField(max_length=50, label='Método de pago')
    sede_donde_paga = forms.ModelChoiceField(queryset=Sede.objects.none(), label='Sede receptora')

    def __init__(self, *args, sedes=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = INPUT_CLASS
        self.fields['sede_donde_paga'].queryset = sedes if sedes is not None else Sede.objects.none()
