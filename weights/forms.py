from functools import lru_cache

from django import forms
from django.forms.formsets import DELETION_FIELD_NAME
from django.forms.models import BaseInlineFormSet, inlineformset_factory

from alors.models import Issue

from .models import (
    Exercise,
    WeightsWorkout,
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    format_seconds,
)

# A new workout starts with one exercise row, and a freshly added exercise
# with this many sets, each prefilled.
DEFAULT_EXERCISE_COUNT = 1
DEFAULT_SET_COUNT = 3
DEFAULT_REPS = 8
# New sets are prefilled with this rest, which can be cleared to record none.
DEFAULT_REST_SECONDS = 45

# Times are typed into a single box as "m:ss", e.g. "1:30" for ninety seconds.
TIME_ERROR = "Enter a time as minutes and seconds, for example 1:30."


def parse_seconds(value):
    """A "m:ss" or plain seconds entry as a number of seconds, or ``None``.

    Raises ``ValueError`` for anything else, e.g. "1:75" or "later".
    """
    value = (value or "").strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) > 2 or not all(part.strip().isdigit() for part in parts):
        raise ValueError(value)
    if len(parts) == 1:
        return int(parts[0])
    minutes, seconds = (int(part) for part in parts)
    if seconds > 59:
        raise ValueError(value)
    return minutes * 60 + seconds


class MinuteSecondField(forms.CharField):
    """A time typed as "m:ss", kept as typed and read with `parse_seconds`."""

    def clean(self, value):
        value = super().clean(value)
        if value:
            try:
                parse_seconds(value)
            except ValueError:
                raise forms.ValidationError(TIME_ERROR)
        return value


@lru_cache(maxsize=1)
def _exercise_choices():
    """Every catalogue exercise plus an empty choice, sorted by name."""
    return [("", "Choose an exercise…")] + Exercise.choices()


class WeightsWorkoutForm(forms.ModelForm):
    """The workout's own fields (currently just its title)."""

    class Meta:
        model = WeightsWorkout
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Leg day",
                }
            ),
        }


class WeightsWorkoutIssueForm(forms.Form):
    """Pick one of the issues not yet attached to a weights workout."""

    issue = forms.ModelChoiceField(
        queryset=Issue.objects.none(),
        label="Issue",
        empty_label="Choose an issue…",
        widget=forms.Select(attrs={"class": "form-select form-select-sm w-auto"}),
    )

    def __init__(self, *args, workout=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workout is None:
            self.fields["issue"].queryset = Issue.objects.all()
        else:
            self.fields["issue"].queryset = Issue.objects.exclude(
                weights_workouts=workout
            )


class WeightsWorkoutExerciseForm(forms.ModelForm):
    """One row of a workout: an exercise picked from the catalogue."""

    exercise_id = forms.TypedChoiceField(coerce=int, label="Exercise")
    superset = forms.CharField(
        required=False,
        max_length=1,
        label="Superset",
        widget=forms.HiddenInput,
        help_text="The letter of the superset this row is grouped into, if any.",
    )

    class Meta:
        model = WeightsWorkoutExercise
        fields = ["exercise_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["exercise_id"].choices = _exercise_choices()
        if self.instance.superset_id and not self.is_bound:
            self.initial["superset"] = self.instance.superset.letter
        for name, field in self.fields.items():
            if name not in ("id", "superset"):
                field.widget.attrs["class"] = "form-select"

    def clean_superset(self):
        """Upper case the posted letter, treating a blank one as no superset."""
        return (self.cleaned_data["superset"] or "").strip().upper()


class HideDeleteCheckbox:
    """Keep the row's removal checkbox out of sight behind its remove button.

    The checkbox is added to the form by the formset, after the form's own
    ``__init__`` has run, so it has to be styled from here instead.
    """

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if DELETION_FIELD_NAME in form.fields:
            form.fields[DELETION_FIELD_NAME].widget.attrs["class"] = "d-none"


class BaseWeightsWorkoutExerciseFormSet(HideDeleteCheckbox, BaseInlineFormSet):
    """The workout's exercises, at least one of which has to be kept."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(
            form.cleaned_data.get("exercise_id")
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ):
            raise forms.ValidationError("Add at least one exercise to the workout.")


WeightsWorkoutExerciseFormSet = inlineformset_factory(
    WeightsWorkout,
    WeightsWorkoutExercise,
    form=WeightsWorkoutExerciseForm,
    formset=BaseWeightsWorkoutExerciseFormSet,
    extra=DEFAULT_EXERCISE_COUNT,
    can_delete=True,
)


class WeightsWorkoutSetForm(forms.ModelForm):
    """One set of an exercise: reps (or a time for timed exercises) and weight."""

    duration = MinuteSecondField(
        required=False,
        label="Time",
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "style": "width:5rem",
                "placeholder": "m:ss",
                "title": "minutes:seconds",
            }
        ),
    )
    rest = MinuteSecondField(
        required=False,
        label="Rest",
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "style": "width:5rem",
            }
        ),
    )

    class Meta:
        model = WeightsWorkoutSet
        fields = ["reps", "weight", "completed"]
        widgets = {
            "reps": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "1",
                    "style": "width:5rem",
                }
            ),
            "weight": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "0",
                    "step": "0.5",
                    "style": "width:5rem",
                }
            ),
            "completed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, timed=False, actual=False, **kwargs):
        self.timed = timed
        self.actual = actual
        super().__init__(*args, **kwargs)
        # Only a workout that has been done has sets to tick off; leaving the
        # field out elsewhere keeps whatever was saved on the plan alone.
        if not actual:
            self.fields.pop("completed", None)
        # A timed set records a time instead of reps, so don't prefill reps.
        if self.instance.pk is None and not self.is_bound and not timed:
            self.initial["reps"] = DEFAULT_REPS
        if self.instance.duration_seconds is not None:
            self.initial["duration"] = format_seconds(self.instance.duration_seconds)
        if self.instance.rest_seconds is not None:
            self.initial["rest"] = format_seconds(self.instance.rest_seconds)
        elif self.instance.pk is None and not self.is_bound:
            self.initial["rest"] = format_seconds(DEFAULT_REST_SECONDS)

    def total_duration(self):
        """The entered time as a single number of seconds."""
        cleaned = getattr(self, "cleaned_data", None) or {}
        return parse_seconds(cleaned.get("duration")) or 0

    def total_rest(self):
        """The entered rest in seconds, or ``None`` when it was left blank."""
        cleaned = getattr(self, "cleaned_data", None) or {}
        return parse_seconds(cleaned.get("rest")) or None

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.timed:
            instance.duration_seconds = self.total_duration()
            instance.reps = None
        else:
            instance.duration_seconds = None
        instance.rest_seconds = self.total_rest()
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BaseWeightsWorkoutSetFormSet(HideDeleteCheckbox, BaseInlineFormSet):
    """An exercise's sets, each removable with the button on its row."""


# Sets of an existing exercise: only the saved rows.
WeightsWorkoutSetFormSet = inlineformset_factory(
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    form=WeightsWorkoutSetForm,
    formset=BaseWeightsWorkoutSetFormSet,
    extra=0,
    can_delete=True,
)

# Sets of a new exercise: a few prefilled rows to fill in.
DefaultWeightsWorkoutSetFormSet = inlineformset_factory(
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    form=WeightsWorkoutSetForm,
    formset=BaseWeightsWorkoutSetFormSet,
    extra=DEFAULT_SET_COUNT,
    can_delete=True,
)
