from django import forms
from django.utils import timezone
from .models import (
    Comment,
    Issue,
    Label,
    PlannedWorkout,
    SavedWorkout,
    UserProfile,
    Workout,
)
from datetime import timedelta
from django.utils import timezone
import pytz

import calendar

class CalendarForm(forms.Form):
    d = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=False,
    )
    r = forms.CharField(required=False, empty_value="w")

    def is_valid(self):
        valid = super().is_valid()
        date = self.cleaned_data.get("d")
        date_range = self.cleaned_data.get("r")
        date = date if date else timezone.now().date()
        dates = {
            "today": timezone.localdate(),
        }
        if date_range == "w":
            start = date - timedelta(days=date.weekday())
            dates.update({
                "start": start,
                "end": start + timedelta(days=6),
                "previous": start - timedelta(days=1),
                "next": start + timedelta(days=6 + 7),
            })
        if date_range == "m":
            start = date - timedelta(days=date.day - 1)
            days_in_month = calendar.monthrange(date.year, date.month)[1]
            dates.update({
                "start": start,
                "end": start + timedelta(days=days_in_month - 1),
                "previous": start - timedelta(days=days_in_month - 1),
                "next": start + timedelta(days=days_in_month + 1), 
            })

        self.cleaned_data["start_end_dates"] = {
            k: v.strftime("%Y-%m-%d") for k, v in dates.items()
        }
        self.cleaned_data["list_dates"] = [
            (dates["start"] + timezone.timedelta(days=i))
            for i in range((dates["end"] - dates["start"]).days + 1)
        ]
        return valid


class SavedWorkoutSelect(forms.Select):
    """Select whose options carry each saved workout's text in ``data-text``.

    The planned-workout page reads it to fill the notes field client-side, so
    the texts are passed in from :class:`PlannedWorkoutForm`.
    """

    def __init__(self, texts=None, **kwargs):
        super().__init__(**kwargs)
        self.texts = texts or {}

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        text = self.texts.get(str(value))
        if text:
            option["attrs"]["data-text"] = text
        return option


class PlannedWorkoutForm(forms.ModelForm):
    saved_workout = forms.ModelChoiceField(
        queryset=SavedWorkout.objects.all(),
        required=False,
        label="Copy over saved workout",
        widget=SavedWorkoutSelect(attrs={"class": "form-select"}),
        help_text="Pick a saved workout to copy its text into the notes. Click Settings 👉 Saved workouts to add some in.",
    )

    class Meta:
        model = PlannedWorkout
        fields = [
            "title",
            "workout_type",
            "is_race",
            "workout_date",
            "total_distance",
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
            "notes": forms.Textarea(attrs={"rows": 10, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show the picker directly above the notes it fills in, and give its
        # options the saved workout's text for the client-side autofill.
        self.fields["saved_workout"].widget.texts = {
            str(pk): text for pk, text in SavedWorkout.objects.values_list("pk", "text")
        }
        names = [name for name in self.fields if name != "saved_workout"]
        names.insert(names.index("notes"), "saved_workout")
        self.order_fields(names)


class SavedWorkoutForm(forms.ModelForm):
    class Meta:
        model = SavedWorkout
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
