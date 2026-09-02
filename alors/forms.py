from django import forms

from .models import PlannedWorkout, WarmUp


class PlannedWorkoutForm(forms.ModelForm):
    class Meta:
        model = PlannedWorkout
        fields = ["title", "workout_type", "workout_date", "total_distance", "warm_up", "notes"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Long run",
                }
            ),
            "workout_type": forms.Select(attrs={"class": "form-select"}),
            "workout_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "total_distance": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "class": "form-control"}
            ),
            "warm_up": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warm_up"].empty_label = "No warm-up"


class WarmUpForm(forms.ModelForm):
    class Meta:
        model = WarmUp
        fields = ["title", "text"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Easy jog",
                }
            ),
            "text": forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
        }
