from django import forms
from django.utils import timezone
from .models import (
    Comment,
    Issue,
    Label,
    PlannedWorkout,
    UserProfile,
    WarmUp,
    Workout,
)
from datetime import timedelta
from django.utils import timezone
import pytz
class CalendarForm(forms.Form):
    d = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=False,
    )

    def is_valid(self):
        valid = super().is_valid()
        date = self.cleaned_data.get("d")
        date = date if date else timezone.now().date()
        dates = {
            "today": timezone.localdate(),
            "start": date - timedelta(days=2),
            "end": date + timedelta(days=4),
            "previous": date - timedelta(days=6),
            "next": date + timedelta(days=6),
        }
        self.cleaned_data["start_end_dates"] = {
            k: v.strftime("%Y-%m-%d") for k, v in dates.items()
        }
        self.cleaned_data["list_dates"] = [
            (dates["start"] + timezone.timedelta(days=i))
            for i in range((dates["end"] - dates["start"]).days + 1)
        ]
        return valid


class PlannedWorkoutForm(forms.ModelForm):
    class Meta:
        model = PlannedWorkout
        fields = [
            "title",
            "workout_type",
            "is_race",
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
            "is_race": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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

    effort_choices = [
        ["1", "1: Very light"],
        ["2", "2: Light"],
        ["3", "3: Light"],
        ["4", "4: Moderate"],
        ["5", "5: Moderate"],
        ["6", "6: Moderate"],
        ["7", "7: Hard"],
        ["8", "8: Hard"],
        ["9", "9: Very hard"],
        ["10", "10: Max effort"],
    ]

    feeling_choices = [
        ["1", "1: Terrible"],
        ["2", "2: Poor"],
        ["3", "3: Normal"],
        ["4", "4: Good"],
        ["5", "5: Great"],
    ]

    effort = forms.TypedChoiceField(
        label="Effort",
        required=False,
        coerce=int,
        empty_value=None,
        choices=[("", "—")] + effort_choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    feeling = forms.TypedChoiceField(
        label="Feeling",
        required=False,
        coerce=int,
        empty_value=None,
        choices=[("", "—")] + feeling_choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Workout
        fields = ["notes", "effort", "feeling", "issues"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
            "issues": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].help_text = "Markdown is supported."
        self.fields["issues"].help_text = "Attach one or more issues to this workout."


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ["title", "colour"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Sore knees",
                }
            ),
            "colour": forms.Select(attrs={"class": "form-select"}),
        }


class LabelForm(forms.ModelForm):
    class Meta:
        model = Label
        fields = ["title", "colour", "start_date", "end_date"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Drinking 🍸 on a beach",
                }
            ),
            "colour": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError("End date must be on or after the start date.")
        if (end - start).days > 100:
            raise forms.ValidationError(
                "End date must be less than 100 days after the start date."
            )
        return cleaned


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["text"]
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].label = "Add a comment"
        self.fields["text"].help_text = "Markdown is supported."


class ProfileForm(forms.ModelForm):
    """Edit a user's role, timezone and email address (email lives on the user)."""

    email = forms.EmailField(
        label="Email address",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    timezone = forms.ChoiceField(
        label="Timezone",
        choices=[(tz, tz) for tz in pytz.all_timezones],
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Your local timezone, used to show dates and times.",
    )

    class Meta:
        model = UserProfile
        fields = ["role", "timezone", "avatar"]
        widgets = {
            "role": forms.Select(attrs={"class": "form-select"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields["email"].initial = self.user.email

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if self.user:
            self.user.email = self.cleaned_data.get("email", "")
            if commit:
                self.user.save(update_fields=["email"])
        return profile
