import copy
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from django.db import models
from django.utils import timezone

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


def format_seconds(total_seconds):
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

    @property
    def is_unilateral(self):
        """Whether this exercise is done one side at a time."""
        return bool(self.attributes.get("is_unilateral"))

    @property
    def instructions(self):
        """How to do the exercise, from the bundled instructions."""
        return self._metadata().get("instructions")

    @property
    def image_url(self):
        """The picture of the exercise, from the bundled instructions."""
        return self._metadata().get("image_url")

    def _metadata(self):
        """The attributes of this exercise's instructions, if it has any."""
        resolved = _catalogue().get(self.id) or {}
        relationships = resolved.get("relationships") or {}
        resources = (relationships.get("instructions") or {}).get("data") or []
        return resources[0].get("attributes", {}) if resources else {}

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


class WorkoutStep:
    """One set to do, in the order the workout is done in.

    A superset is done in rounds: one set of each of its exercises, then a
    single rest at the end of the round. That rest therefore sits on the last
    set of the round, and the sets before it follow straight on.
    """

    def __init__(
        self,
        entry,
        model_set,
        number,
        of,
        timed=False,
        rest_seconds=None,
        round=None,
        rounds=None,
        order=None,
        unilateral=False,
    ):
        self.entry = entry
        self.set = model_set
        self.number = number
        self.of = of
        self.timed = timed
        self.unilateral = unilateral
        self.rest_seconds = rest_seconds
        self.round = round
        self.rounds = rounds
        # Where the set comes in the workout as a whole, set by ``steps``: a
        # superset's sets are not grouped by exercise in the order they are
        # done in.
        self.order = order

    def __repr__(self):
        return f"<WorkoutStep {self.entry} set {self.number} of {self.of}>"

    @property
    def superset(self):
        """The superset this step is part of, if any."""
        return self.entry.superset

    @property
    def rest(self):
        """The rest to take after this step as ``m:ss``, or ``None``."""
        return format_seconds(self.rest_seconds)

    @property
    def sides(self):
        """How many sides the set is timed over: two when done one at a time."""
        return 2 if self.timed and self.unilateral else 1

    @property
    def done(self):
        """Whether this set has been done."""
        return self.set.completed


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
    started_at = models.DateTimeField(
        "started at",
        null=True,
        blank=True,
        help_text="When the workout was started.",
    )
    finished_at = models.DateTimeField(
        "finished at",
        null=True,
        blank=True,
        help_text="When the workout's last set was done.",
    )
    completed = models.BooleanField(
        "completed",
        default=False,
        help_text="Whether the workout has been finished.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "weights workout"
        verbose_name_plural = "weights workouts"
        indexes = [
            models.Index(fields=["is_actual"], name="weights_actual_idx"),
            models.Index(fields=["completed"], name="weights_completed_idx"),
            models.Index(fields=["started_at"], name="weights_started_idx"),
        ]

    def __str__(self):
        created = (
            self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "unsaved"
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

    def steps(self):
        """Every set to do, in the order the workout is done in.

        Sets with nothing to do (no reps and no time) are left out.
        """
        steps = []
        for superset, entries in self.exercise_groups():
            sets_of = [list(entry.sets.all()) for entry in entries]
            if superset is None:
                for entry, model_sets in zip(entries, sets_of):
                    steps.extend(self._sets_of(entry, model_sets))
                continue
            rounds = max((len(model_sets) for model_sets in sets_of), default=0)
            for index in range(rounds):
                doing = [
                    (entry, model_sets[index], len(model_sets))
                    for entry, model_sets in zip(entries, sets_of)
                    if index < len(model_sets)
                ]
                for position, (entry, model_set, of) in enumerate(doing):
                    steps.append(
                        WorkoutStep(
                            entry=entry,
                            model_set=model_set,
                            number=index + 1,
                            of=of,
                            timed=entry.exercise.is_timed if entry.exercise else False,
                            unilateral=(
                                entry.exercise.is_unilateral
                                if entry.exercise
                                else False
                            ),
                            # Only the last set of the round is followed by a rest.
                            rest_seconds=(
                                superset.rest_seconds
                                if position == len(doing) - 1
                                else None
                            ),
                            round=index + 1,
                            rounds=rounds,
                        )
                    )
        for order, step in enumerate(steps):
            step.order = order
        return steps

    def step_groups(self):
        """Every set to do, grouped by the exercise it belongs to, in order.

        This is what the perform page shows, one exercise at a time; a
        superset's exercises each come back as their own group, in the order
        their first set is met.
        """
        groups = {}
        ordered = []
        for step in self.steps():
            if step.entry.pk in groups:
                groups[step.entry.pk].append(step)
            else:
                groups[step.entry.pk] = [step]
                ordered.append((step.entry, groups[step.entry.pk]))
        return ordered

    def _sets_of(self, entry, model_sets):
        """One exercise's sets as steps, each followed by its own rest."""
        return [
            WorkoutStep(
                entry=entry,
                model_set=model_set,
                number=number,
                of=len(model_sets),
                timed=entry.exercise.is_timed if entry.exercise else False,
                unilateral=entry.exercise.is_unilateral if entry.exercise else False,
                rest_seconds=model_set.rest_seconds,
            )
            for number, model_set in enumerate(model_sets, start=1)
            if model_set.reps is not None or model_set.duration_seconds is not None
        ]

    def completed_set_count(self):
        """How many of the workout's sets have been done."""
        return sum(
            1
            for entry in self.exercises.all()
            for model_set in entry.sets.all()
            if model_set.completed
        )

    def mark_started(self):
        """Stamp the moment the workout was started, once."""
        if self.started_at is None:
            self.started_at = timezone.now()
            self.save(update_fields=["started_at"])

    def mark_finished(self):
        """Complete the workout once every set has been ticked off.

        Finishing by hand is :meth:`complete`; this only picks up a workout
        whose last set was ticked off as it was done.
        """
        steps = self.steps()
        if not self.completed and steps and all(step.done for step in steps):
            self.complete()

    def elapsed_seconds(self):
        """How long the workout has been going, or how long it took.

        A finished workout stops at the time it was finished, and a workout
        that was never started has no time to show.
        """
        if self.started_at is None:
            return None
        stopped = (
            self.finished_at if self.completed and self.finished_at else timezone.now()
        )
        return max(0, int((stopped - self.started_at).total_seconds()))

    @property
    def elapsed(self):
        """The workout's time so far as ``m:ss``, or ``None``."""
        return format_seconds(self.elapsed_seconds())

    def complete(self):
        """Mark the workout finished, recording when it was."""
        self.completed = True
        self.finished_at = timezone.now()
        self.save(update_fields=["completed", "finished_at"])

    def reopen(self):
        """Put a finished workout back in progress."""
        self.completed = False
        self.finished_at = None
        self.save(update_fields=["completed", "finished_at"])

    def get_date_as_str(self):
        return self.started_at.strftime("%Y-%m-%d")

    @property
    def workout_type(self):
        return "strength"


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
        return format_seconds(self.rest_seconds)


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
        return format_seconds(self.duration_seconds)

    @property
    def rest(self):
        """The set's rest as ``m:ss``, or ``None``."""
        return format_seconds(self.rest_seconds)
