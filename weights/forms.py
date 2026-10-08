from functools import lru_cache

from django import forms
from django.forms.models import BaseInlineFormSet, inlineformset_factory

from .models import Exercise, WeightsWorkout, WeightsWorkoutExercise, WeightsWorkoutSet

# A freshly added exercise starts with this many sets, each prefilled.
DEFAULT_SET_COUNT = 3
DEFAULT_REPS = 8
# New sets are prefilled with this rest, which can be cleared to record none.
DEFAULT_REST_SECONDS = 45


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
            if name == "DELETE":
                field.widget.attrs["class"] = "form-check-input"
            elif name not in ("id", "superset"):
                field.widget.attrs["class"] = "form-select"

    def clean_superset(self):
        """Upper case the posted letter, treating a blank one as no superset."""
        return (self.cleaned_data["superset"] or "").strip().upper()


class BaseWeightsWorkoutExerciseFormSet(BaseInlineFormSet):
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
    extra=3,
    can_delete=True,
)


class WeightsWorkoutSetForm(forms.ModelForm):
    """One set of an exercise: reps (or a time for timed exercises) and weight."""

    minutes = forms.IntegerField(
        required=False,
        min_value=0,
        label="Minutes",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm",
                "min": "0",
                "placeholder": "min",
            }
        ),
    )
    seconds = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=59,
        label="Seconds",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm",
                "min": "0",
                "max": "59",
                "placeholder": "sec",
            }
        ),
    )
    rest_minutes = forms.IntegerField(
        required=False,
        min_value=0,
        label="Rest minutes",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm",
                "min": "0",
                "placeholder": "0",
            }
        ),
    )
    rest_seconds = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=59,
        label="Rest seconds",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm",
                "min": "0",
                "max": "59",
                "placeholder": "0",
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
                    "placeholder": "reps",
                }
            ),
            "weight": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "min": "0",
                    "step": "0.5",
                    "placeholder": "weight",
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
        # The "remove" button toggles this checkbox; keep it out of the way.
        if "DELETE" in self.fields:
            self.fields["DELETE"].widget.attrs["class"] = "d-none"
        # A timed set records a time instead of reps, so don't prefill reps.
        if self.instance.pk is None and not self.is_bound and not timed:
            self.initial["reps"] = DEFAULT_REPS
        if self.instance.duration_seconds is not None:
            minutes, seconds = divmod(self.instance.duration_seconds, 60)
            self.initial["minutes"] = minutes
            self.initial["seconds"] = seconds
        if self.instance.rest_seconds is not None:
            minutes, seconds = divmod(self.instance.rest_seconds, 60)
            self.initial["rest_minutes"] = minutes
            self.initial["rest_seconds"] = seconds
        elif self.instance.pk is None and not self.is_bound:
            self.initial["rest_seconds"] = DEFAULT_REST_SECONDS

    def total_duration(self):
        """The entered minutes and seconds as a single number of seconds."""
        cleaned = getattr(self, "cleaned_data", None) or {}
        return (cleaned.get("minutes") or 0) * 60 + (cleaned.get("seconds") or 0)

    def total_rest(self):
        """The entered rest in seconds, or ``None`` when it was left blank."""
        cleaned = getattr(self, "cleaned_data", None) or {}
        minutes = cleaned.get("rest_minutes") or 0
        seconds = cleaned.get("rest_seconds") or 0
        if not minutes and not seconds:
            return None
        return minutes * 60 + seconds

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


# Sets of an existing exercise: only the saved rows.
WeightsWorkoutSetFormSet = inlineformset_factory(
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    form=WeightsWorkoutSetForm,
    extra=0,
    can_delete=True,
)

# Sets of a new exercise: a few prefilled rows to fill in.
DefaultWeightsWorkoutSetFormSet = inlineformset_factory(
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    form=WeightsWorkoutSetForm,
    extra=DEFAULT_SET_COUNT,
    can_delete=True,
)
