from django import forms

from .models import Health


class HealthForm(forms.ModelForm):
    """Add or edit a set of health measurements."""

    class Meta:
        model = Health
        fields = ["weight", "systolic", "diastolic", "resting_heart_rate"]
        widgets = {
            "weight": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.1",
                    "min": "0",
                    "placeholder": "e.g. 176.4",
                }
            ),
            "systolic": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "placeholder": "e.g. 120"}
            ),
            "diastolic": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "placeholder": "e.g. 80"}
            ),
            "resting_heart_rate": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "placeholder": "e.g. 52"}
            ),
        }
