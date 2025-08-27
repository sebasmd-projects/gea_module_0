from django import forms

from .models import ProofOfLifeModel


class ProofOfLifeForm(forms.ModelForm):
    """
    Formulario con validación Bootstrap 5.3.3 para la prueba de vida.
    """

    class Meta:
        model = ProofOfLifeModel
        fields = (
            "first_name",
            "last_name",
            "pol_confirmed",
        )
        labels = {
            "first_name": "Nombres*",
            "last_name": "Apellidos*",
            "pol_confirmed": "Confirmo la prueba de vida (Proof of life, POL)*",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "pol_confirmed": forms.CheckboxInput(
                attrs={"class": "form-check-input", "required": "required"}
            ),
        }

    def clean_pol_confirmed(self):
        confirmed = self.cleaned_data.get("pol_confirmed")
        if confirmed is not True:
            raise forms.ValidationError(
                "Aceptar la prueba de vida es obligatorio para continuar."
            )
        return confirmed