from django import forms

from .models import PlannedWorkout


class PlannedWorkoutForm(forms.ModelForm):
    class Meta:
        model = PlannedWorkout
        fields = ["workout_type", "workout_date", "total_distance", "warm_up", "notes"]
        widgets = {
            "workout_type": forms.Select(attrs={"class": "form-select"}),
            "workout_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "total_distance": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "class": "form-control"}
            ),
            "warm_up": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }
