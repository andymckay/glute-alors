from django import forms
from django.contrib.auth import get_user_model
from django.db.models.utils import get_blank_choice_label
from django.utils import timezone
from .models import (
    Comment,
    Issue,
    Label,
    PlannedWorkout,
    SavedWorkout,
    Status,
    UserProfile,
    Workout,
)
from datetime import timedelta
from django.utils import timezone
import pytz
from .utils import today

import calendar
from django.http import QueryDict
from urllib.parse import urlencode


class CalendarForm(forms.Form):
    d = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=False,
    )
    r = forms.CharField(required=False, empty_value="m")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.user = self.request.user if self.request else None
        super(CalendarForm, self).__init__(*args, **kwargs)

    def is_valid(self):
        valid = super().is_valid()
        date = self.cleaned_data.get("d")
        date_range = self.cleaned_data.get("r")
        date = date if date else today(self.user)
        dates = {
            "today": today(self.user),
        }
        if date_range == "w":
            start = date - timedelta(days=date.weekday())
            dates.update(
                {
                    "start": start,
                    "end": start + timedelta(days=6),
                    "previous": start - timedelta(days=1),
                    "next": start + timedelta(days=6 + 7),
                }
            )
        if date_range == "m":
            # In calendar view we go from Monday to Sunday, ensuring we show all
            # the days of the month. So might be longer than a month.
            start_of_month = date - timedelta(days=date.day - 1)
            end_previous_month = start_of_month - timedelta(days=1)
            start_previous_month = end_previous_month - timedelta(
                days=end_previous_month.day - 1
            )

            days_in_month = calendar.monthrange(date.year, date.month)[1]
            end_of_month = start_of_month + timedelta(days=days_in_month - 1)
            start_next_month = end_of_month + timedelta(days=1)
            end_next_month = start_next_month + timedelta(
                days=calendar.monthrange(start_next_month.year, start_next_month.month)[
                    1
                ]
                - 1
            )

            start = start_previous_month - timedelta(
                days=start_previous_month.weekday()
            )  # Start on a Monday
            end = end_next_month + timedelta(
                days=(6 - end_next_month.weekday())
            )  # End on a Sunday
            dates.update(
                {
                    "start": start,
                    "end": end,
                    "previous": start_of_month - timedelta(days=days_in_month - 1),
                    "next": end_of_month + timedelta(days=1),
                    "end_next_month": end_next_month,
                    "start_previous_month": start_previous_month
                }
            )

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


class PlannedWorkoutFieldsForm(forms.ModelForm):
    """The editable planned-workout fields, shared by the forms below."""

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


class PlannedWorkoutForm(PlannedWorkoutFieldsForm):
    saved_workout = forms.ModelChoiceField(
        queryset=SavedWorkout.objects.all(),
        required=False,
        label="Copy over saved workout",
        widget=SavedWorkoutSelect(attrs={"class": "form-select"}),
        help_text="Pick a saved workout to copy its text into the notes. Click Settings 👉 Saved workouts to add some in.",
    )

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


class PlannedWorkoutModalForm(PlannedWorkoutFieldsForm):
    """Add or edit a planned workout in a calendar Bootstrap modal.

    It keeps the saved-workout picker so a user can copy a saved workout's
    text into the notes, just like on the add/edit page. The picker is built
    from plain in-memory choices, not a queryset, so a calendar full of modals
    does not run a query per form.
    """

    saved_workout = forms.ChoiceField(
        required=False,
        label="Copy over saved workout",
        widget=SavedWorkoutSelect(attrs={"class": "form-select"}),
        help_text="Pick a saved workout to copy its text into the notes. Click Settings 👉 Saved workouts to add some in.",
    )

    def __init__(
        self, *args, saved_workout_choices=(), saved_workout_texts=None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        # A shorter notes box keeps the modal a sensible height.
        self.fields["notes"].widget.attrs["rows"] = 5
        self.fields["saved_workout"].choices = [
            ("", get_blank_choice_label()),
            *saved_workout_choices,
        ]
        self.fields["saved_workout"].widget.texts = saved_workout_texts or {}
        names = [name for name in self.fields if name != "saved_workout"]
        names.insert(names.index("notes"), "saved_workout")
        self.order_fields(names)


class PlannedWorkoutUpdateForm(PlannedWorkoutFieldsForm):
    """Partial update of a planned workout, used by the calendar JSON endpoint.

    Every field is optional so a caller can change just one of them.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Everything is optional except the date, which the model requires.
        for name, field in self.fields.items():
            if name != "workout_date":
                field.required = False


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
    """Edit the log fields and linked issues of a completed workout.

    When the workout has a matching planned run, the form also carries that
    plan's status so both can be changed on the same page.
    """

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
    planned_status = forms.ChoiceField(
        label="Planned workout status",
        required=False,
        choices=[("", "—")] + list(Status.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=(
            "Whether the matching planned workout was done, missed, over or "
            "under."
        ),
    )

    class Meta:
        model = Workout
        fields = ["notes", "effort", "feeling", "issues"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
            "issues": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, planned=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.planned = planned
        self.fields["notes"].help_text = "Markdown is supported."
        self.fields["issues"].help_text = "Attach one or more issues to this workout."
        if planned is None:
            # The status of a planned workout can only be edited when there is
            # one to edit.
            del self.fields["planned_status"]
            return
        self.fields["planned_status"].initial = planned.status
        names = list(self.fields)
        names.remove("planned_status")
        names.insert(names.index("feeling") + 1, "planned_status")
        self.order_fields(names)

    def save(self, commit=True):
        workout = super().save(commit=commit)
        if commit and self.planned is not None:
            status = self.cleaned_data.get("planned_status", "")
            # Saving the workout recomputes the plan's status from the
            # distance, so compare against what was just stored and let the
            # value shown on the form win.
            try:
                self.planned.refresh_from_db(fields=["status"])
            except PlannedWorkout.DoesNotExist:
                return workout
            if self.planned.status != status:
                self.planned.status = status
                self.planned._notification_actor = getattr(
                    self.instance, "_notification_actor", None
                )
                self.planned.save(update_fields=["status"])
        return workout


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
    """Edit a user's timezone, units, email subscriptions and email address.

    The email address itself lives on the user, not the profile.
    """

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
        fields = [
            "avatar",
            "visibility",
            "timezone",
            "units",
            "show_add_plan",
            "send_daily_email",
            "send_comment_email",
        ]
        widgets = {
            "visibility": forms.SelectMultiple(
                attrs={"class": "form-select", "size": 8}
            ),
            "units": forms.Select(attrs={"class": "form-select"}),
            "show_add_plan": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "send_daily_email": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "send_comment_email": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields["email"].initial = self.user.email
            # Everyone else who could be shown the profile; superusers already
            # see everything and have no need of it.
            self.fields["visibility"].queryset = (
                get_user_model()
                .objects.filter(is_superuser=False)
                .exclude(pk=self.user.pk)
                .order_by("username")
            )

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if self.user:
            self.user.email = self.cleaned_data.get("email", "")
            if commit:
                self.user.save(update_fields=["email"])
        return profile
