from django import forms
from django.utils import timezone
from .models import Issue, PlannedWorkout, WarmUp, Workout
from .utils import daily, weekly, monthly


class CalendarForm(forms.Form):
    d = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=False,
    )
    v = forms.ChoiceField(
        choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
    )

    def is_valid(self):
        valid = super().is_valid()
        dates_lookup = {
            "daily": daily,
            "weekly": weekly,
            "monthly": monthly,
        }
        date = self.cleaned_data.get("d")
        date = (
            date.strftime("%Y-%m-%d")
            if date
            else timezone.now().date().strftime("%Y-%m-%d")
        )
        view = self.cleaned_data.get("v")
        dates = dates_lookup[view or "weekly"](date)
        self.cleaned_data["start_end_dates"] = dates
        self.cleaned_data["list_dates"] = [(dates["start"] + timezone.timedelta(days=i)).date() for i in range((dates["end"] - dates["start"]).days + 1)]
        return valid


class PlannedWorkoutForm(forms.ModelForm):
    class Meta:
        model = PlannedWorkout
        fields = [
            "title",
            "workout_type",
            "workout_date",
            "total_distance",
            "warm_up",
            "notes",
        ]
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


class WorkoutEditForm(forms.ModelForm):
    """Edit the log fields and linked issues of a completed workout."""

    class Meta:
        model = Workout
        fields = ["notes", "effort", "feeling", "issues"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
            "effort": forms.NumberInput(
                attrs={"min": 1, "max": 10, "step": 1, "class": "form-control"}
            ),
            "feeling": forms.NumberInput(
                attrs={"min": 1, "max": 5, "step": 1, "class": "form-control"}
            ),
            "issues": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].help_text = "Markdown is supported."
        self.fields["issues"].help_text = "Attach one or more issues to this workout."


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ["title", "text"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Sore knees",
                }
            ),
            "text": forms.Textarea(attrs={"rows": 6, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].help_text = "Markdown is supported."
