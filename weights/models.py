import copy
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from django.db import models

from core.models import CreatedByModel

# The directory holding the bundled JSON:API dumps.
FITBOD_DIR = Path(__file__).resolve().parent / "fitbod"

# Exercise relationship -> the bucket in ``_index()`` that resolves it.
_RELATIONSHIPS = {
    "equipment": "equipment",
    "exercise_categories": "categories",
    "exercise_categorizations": "categorizations",
    "exercise_equipments": "equipment_joins",
    "primary_muscle_groups": "primary_muscles",
    "secondary_muscle_groups": "secondary_muscles",
    "instructions": "instructions",
}


@lru_cache(maxsize=None)
def _load(name):
    """The ``data`` list of a bundled JSON:API dump.

    Enrichment is best-effort, so a dump that is not present yields nothing.
    """
    try:
        payload = json.loads((FITBOD_DIR / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    return rows or []


def _related_id(row, key):
    """The id at the far end of a JSON:API relationship.

    The bundled dumps use ``{"links": {"related": ".../123"}}``; the live API
    nests ``{"data": {"id": 123}}``.  Both are accepted.
    """
    relationship = (row.get("relationships") or {}).get(key) or {}

    data = relationship.get("data")
    if isinstance(data, dict) and data.get("id") is not None:
        return str(data["id"])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if data[0].get("id") is not None:
            return str(data[0]["id"])

    related = (relationship.get("links") or {}).get("related")
    if related:
        return str(related).rstrip("/").rsplit("/", 1)[-1]
    return None


@lru_cache(maxsize=1)
def _index():
    """Lookup and join tables keyed by exercise id, built once per process."""
    equipment = {str(row["id"]): row for row in _load("equipment.json")}
    categories = {str(row["id"]): row for row in _load("exercise_categories.json")}
    muscles = {str(row["id"]): row for row in _load("muscle_groups.json")}

    equipment_joins = defaultdict(list)
    equipment_refs = defaultdict(list)
    for row in _load("exercise_equipment.json"):
        exercise_id = _related_id(row, "exercise")
        equipment_id = _related_id(row, "equipment")
        if exercise_id:
            equipment_joins[exercise_id].append(row)
            if equipment_id in equipment:
                equipment_refs[exercise_id].append(equipment[equipment_id])

    categorizations = defaultdict(list)
    category_refs = defaultdict(list)
    for row in _load("exercise_categorizations.json"):
        exercise_id = _related_id(row, "exercise")
        category_id = _related_id(row, "exercise_category")
        if exercise_id:
            categorizations[exercise_id].append(row)
            if category_id in categories:
                category_refs[exercise_id].append(categories[category_id])

    def muscle_refs(name):
        refs = defaultdict(list)
        for row in _load(name):
            exercise_id = _related_id(row, "exercise")
            muscle_id = _related_id(row, "muscle_group")
            if exercise_id and muscle_id in muscles:
                refs[exercise_id].append(muscles[muscle_id])
        return refs

    instructions = defaultdict(list)
    for row in _load("exercise_instructions_metadata.json"):
        exercise_id = _related_id(row, "exercise")
        if exercise_id:
            instructions[exercise_id].append(row)

    return {
        "equipment": equipment_refs,
        "categories": category_refs,
        "categorizations": categorizations,
        "equipment_joins": equipment_joins,
        "primary_muscles": muscle_refs("exercise_primary_muscle_groups.json"),
        "secondary_muscles": muscle_refs("exercise_secondary_muscle_groups.json"),
        "instructions": instructions,
    }


def _resolve(row):
    """A copy of ``row`` with each known relationship resolved in place."""
    index = _index()
    resolved = copy.deepcopy(row)
    relationships = resolved.setdefault("relationships", {})
    exercise_id = str(resolved.get("id"))
    for key, bucket in _RELATIONSHIPS.items():
        related = index[bucket].get(exercise_id, [])
        relationships[key] = {"data": copy.deepcopy(related)}
    return resolved


@lru_cache(maxsize=1)
def _catalogue():
    """The resolved catalogue keyed by exercise id, built once per process."""
    return {str(row.get("id")): _resolve(row) for row in _load("exercises.json")}


@lru_cache(maxsize=1)
def _timed_ids():
    """The ids of every exercise whose ``is_timed`` attribute is set."""
    return frozenset(
        int(exercise_id)
        for exercise_id, row in _catalogue().items()
        if row["attributes"].get("is_timed")
    )


def load():
    """Load the bundled JSON and build the caches.

    Called once when the server starts (see
    :class:`weights.apps.WeightsConfig`) so the first request never pays for
    parsing and joining the dumps.
    """
    _index()
    _catalogue()


def _mmss(total_seconds):
    """A number of seconds as ``m:ss``, or ``None`` when unset."""
    if total_seconds is None:
        return None
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def superset_groups(items, superset_of):
    """Group ``items`` into supersets, keeping the order they arrive in.

    ``superset_of`` returns the superset an item belongs to, or ``None``; items
    without one each form their own group.
    """
    groups = {}
    ordered = []
    for item in items:
        superset = superset_of(item)
        if superset is None:
            ordered.append((None, [item]))
        elif superset.pk in groups:
            groups[superset.pk][1].append(item)
        else:
            group = (superset, [item])
            groups[superset.pk] = group
            ordered.append(group)
    return ordered


class Exercise:
    """A single exercise backed by the bundled JSON (no database)."""

    def __init__(self, row):
        self.row = row

    def __repr__(self):
        return f"<Exercise {self.id} {self.name!r}>"

    @property
    def id(self):
        return str(self.row.get("id"))

    @property
    def attributes(self):
        return self.row.get("attributes") or {}

    @property
    def name(self):
        return self.attributes.get("name")

    @property
    def slug(self):
        return self.attributes.get("slug")

    @property
    def is_timed(self):
        """Whether this exercise is measured in time rather than reps."""
        return bool(self.attributes.get("is_timed"))

    @classmethod
    def timed_ids(cls):
        """The ids of every timed exercise in the catalogue."""
        return _timed_ids()

    @classmethod
    def get_exercises(cls):
        """Every exercise as JSON, with relationships resolved in place."""
        return copy.deepcopy(list(_catalogue().values()))

    @classmethod
    def get(cls, exercise_id):
        """A single :class:`Exercise` by its id, or ``None``."""
        wanted = str(exercise_id)
        for row in _load("exercises.json"):
            if str(row.get("id")) == wanted:
                return cls(row)
        return None

    @classmethod
    def choices(cls):
        """``[(id, name)]`` for every exercise, sorted by name."""
        return sorted(
            (
                (int(exercise_id), row["attributes"].get("name", ""))
                for exercise_id, row in _catalogue().items()
            ),
            key=lambda choice: choice[1].lower(),
        )

    def get_exercise(self):
        """This exercise as JSON, with relationships resolved in place."""
        resolved = _catalogue().get(self.id)
        return copy.deepcopy(resolved if resolved is not None else _resolve(self.row))


class WeightsWorkout(CreatedByModel):
    """A workout built from exercises in the catalogue."""

    title = models.CharField(
        "title",
        max_length=200,
        help_text="A short name for the workout.",
    )
    plan = models.ForeignKey(
        "self",
        verbose_name="plan",
        related_name="sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="The planned workout this one was started from.",
    )
    is_actual = models.BooleanField(
        "actual",
        default=False,
        help_text="Whether this workout has been done, rather than planned.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "weights workout"
        verbose_name_plural = "weights workouts"

    def __str__(self):
        created = (
            self.created_at.strftime("%Y-%m-%d %H:%M")
            if self.created_at
            else "unsaved"
        )
        return f"Weights workout for {self.created_by or 'Anonymous'} ({created})"

    def get_exercises(self):
        """The workout's exercises as JSON, in order."""
        return [
            entry.exercise.get_exercise()
            for entry in self.exercises.all()
            if entry.exercise
        ]

    def exercise_groups(self):
        """The workout's exercises grouped into supersets, in order."""
        return superset_groups(self.exercises.all(), lambda entry: entry.superset)

    def set_count(self):
        """How many sets the workout holds."""
        return sum(len(entry.sets.all()) for entry in self.exercises.all())

    def completed_set_count(self):
        """How many of the workout's sets have been done."""
        return sum(
            1
            for entry in self.exercises.all()
            for model_set in entry.sets.all()
            if model_set.completed
        )


class WeightsWorkoutSuperset(models.Model):
    """Exercises done back-to-back, resting once at the end of each round."""

    workout = models.ForeignKey(
        WeightsWorkout,
        verbose_name="workout",
        related_name="supersets",
        on_delete=models.CASCADE,
        help_text="The workout this superset belongs to.",
    )
    letter = models.CharField(
        "letter",
        max_length=1,
        help_text="Label for the superset, e.g. A.",
    )
    rest_seconds = models.PositiveIntegerField(
        "rest (seconds)",
        null=True,
        blank=True,
        help_text="Rest taken at the end of each round of the superset.",
    )

    class Meta:
        ordering = ["letter"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "letter"], name="unique_superset_letter"
            )
        ]
        verbose_name = "superset"
        verbose_name_plural = "supersets"

    def __str__(self):
        return f"Superset {self.letter}"

    @property
    def rest(self):
        """The superset's rest as ``m:ss``, or ``None``."""
        return _mmss(self.rest_seconds)


class WeightsWorkoutExercise(models.Model):
    """One catalogue exercise, in order, within a :class:`WeightsWorkout`."""

    workout = models.ForeignKey(
        WeightsWorkout,
        verbose_name="workout",
        related_name="exercises",
        on_delete=models.CASCADE,
        help_text="The workout this exercise belongs to.",
    )
    exercise_id = models.PositiveIntegerField(
        "Exercise id",
        help_text="The exercise id from weights/fitbod/exercises.json.",
    )
    position = models.PositiveSmallIntegerField(
        "position",
        default=0,
        help_text="Order of the exercise within the workout.",
    )
    superset = models.ForeignKey(
        WeightsWorkoutSuperset,
        verbose_name="superset",
        related_name="exercises",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="The superset this exercise belongs to, if any.",
    )

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "workout exercise"
        verbose_name_plural = "workout exercises"

    def __str__(self):
        exercise = self.exercise
        return exercise.name if exercise else f"Exercise {self.exercise_id}"

    @property
    def exercise(self):
        """The :class:`Exercise` this row refers to, or ``None``."""
        return Exercise.get(self.exercise_id)


class WeightsWorkoutSet(models.Model):
    """One set of an exercise in a workout: how many reps were done."""

    entry = models.ForeignKey(
        WeightsWorkoutExercise,
        verbose_name="exercise",
        related_name="sets",
        on_delete=models.CASCADE,
        help_text="The exercise this set belongs to.",
    )
    reps = models.PositiveSmallIntegerField(
        "reps",
        null=True,
        blank=True,
        help_text="Repetitions in this set.",
    )
    weight = models.DecimalField(
        "weight",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Weight used for this set, in the units from your profile.",
    )
    duration_seconds = models.PositiveIntegerField(
        "duration (seconds)",
        null=True,
        blank=True,
        help_text="For timed exercises, how long the set lasted.",
    )
    rest_seconds = models.PositiveIntegerField(
        "rest (seconds)",
        null=True,
        blank=True,
        help_text="Optional rest taken after this set.",
    )
    completed = models.BooleanField(
        "done",
        default=False,
        help_text="Whether this set has been done.",
    )
    position = models.PositiveSmallIntegerField(
        "position",
        default=0,
        help_text="Order of the set within the exercise.",
    )

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "workout set"
        verbose_name_plural = "workout sets"

    def __str__(self):
        if self.duration_seconds is not None:
            return f"{self.duration} min"
        reps = self.reps if self.reps is not None else "?"
        return f"{reps} reps"

    @property
    def duration(self):
        """The set's duration as ``m:ss``, or ``None``."""
        return _mmss(self.duration_seconds)

    @property
    def rest(self):
        """The set's rest as ``m:ss``, or ``None``."""
        return _mmss(self.rest_seconds)
