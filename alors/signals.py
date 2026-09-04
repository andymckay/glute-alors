"""Signals that keep WeeklySummary records in sync with planned and completed workouts."""

import datetime

from django.db.models.signals import post_delete, post_save, pre_save
from django.utils.dateparse import parse_date

from .models import PlannedWorkout, WeeklySummary, Workout


def _as_date(value):
    """Coerce a date or a 'YYYY-MM-DD' string to a date."""
    if isinstance(value, datetime.date):
        return value
    return parse_date(str(value))


def _sunday_for(workout_date):
    """Return the Sunday of the week that contains ``workout_date``."""
    workout_date = _as_date(workout_date)
    return workout_date + datetime.timedelta(days=6 - workout_date.weekday())


def _aggregate(queryset, type_label, seconds_of=None):
    """Return (count, total_km, total_seconds, per_type_counts).

    ``seconds_of`` is an optional callable returning the number of seconds
    for each item; when omitted, the time total is zero.
    """
    items = list(queryset)
    total_km = sum(float(item.total_distance or 0) for item in items)
    total_seconds = 0
    if seconds_of is not None:
        total_seconds = int(
            sum((seconds_of(item) or 0) for item in items)
        )
    type_counts = {}
    for item in items:
        label = type_label(item)
        type_counts[label] = type_counts.get(label, 0) + 1
    return len(items), total_km, total_seconds, type_counts


def refresh_weekly_summary(sunday):
    """Recompute and store the weekly summary for the week ending on ``sunday``.

    Planned and completed workouts are aggregated separately so they can be
    kept under distinct keys in the summary JSON.
    """
    week_start = sunday - datetime.timedelta(days=6)

    planned_count, planned_km, planned_seconds, planned_types = _aggregate(
        PlannedWorkout.objects.filter(
            workout_date__gte=week_start,
            workout_date__lte=sunday,
        ),
        lambda workout: workout.get_workout_type_display(),
    )
    (
        workout_count,
        workout_km,
        workout_seconds,
        workout_types,
    ) = _aggregate(
        Workout.objects.filter(
            workout_date__gte=week_start,
            workout_date__lte=sunday,
        ),
        lambda workout: workout.get_workout_type_display(),
        seconds_of=lambda workout: (
            workout.total_time.total_seconds() if workout.total_time else 0
        ),
    )

    if planned_count == 0 and workout_count == 0:
        # Nothing remains for that week, so drop the summary.
        WeeklySummary.objects.filter(date=sunday).delete()
        return

    summary = {
        "planned_workouts": planned_count,
        "planned_distance_km": planned_km,
        "types": planned_types,
        "workouts": workout_count,
        "workout_distance_km": workout_km,
        "workout_total_time_seconds": workout_seconds,
        "workout_types": workout_types,
    }
    WeeklySummary.objects.update_or_create(
        date=sunday,
        defaults={"summary": summary},
    )


def _remember_original_date(sender, instance, **kwargs):
    """Stash the previous date so moved workouts can refresh both weeks."""
    instance._original_workout_date = None
    if instance.pk is not None:
        original = (
            type(instance)
            .objects.filter(pk=instance.pk)
            .values_list("workout_date", flat=True)
            .first()
        )
        instance._original_workout_date = original


def _sync_weekly_summary(sender, instance, **kwargs):
    """Create or update weekly summaries for the workout's week(s)."""
    sundays = {_sunday_for(instance.workout_date)}
    original = getattr(instance, "_original_workout_date", None)
    if original is not None:
        sundays.add(_sunday_for(original))

    for sunday in sundays:
        refresh_weekly_summary(sunday)


def _sync_weekly_summary_on_delete(sender, instance, **kwargs):
    """Refresh the weekly summary after a workout is deleted."""
    workout_date = getattr(instance, "workout_date", None)
    if workout_date is not None:
        refresh_weekly_summary(_sunday_for(workout_date))


for _model in (PlannedWorkout, Workout):
    pre_save.connect(
        _remember_original_date,
        sender=_model,
        dispatch_uid=f"weekly_pre_save_{_model.__name__}",
    )
    post_save.connect(
        _sync_weekly_summary,
        sender=_model,
        dispatch_uid=f"weekly_post_save_{_model.__name__}",
    )
    post_delete.connect(
        _sync_weekly_summary_on_delete,
        sender=_model,
        dispatch_uid=f"weekly_post_delete_{_model.__name__}",
    )
