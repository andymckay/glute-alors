"""Backfill Workout.elevation_gain / elevation_loss from stored FIT data.

Workouts imported before 0007 have both fields NULL, but their ``workout_data``
column already holds the decoded FIT JSON, so the totals can be recomputed
without downloading the .fit files again.

The altitude logic is intentionally duplicated (rather than importing
``parsers.fit.Fit``) so this migration keeps working even if the parser
changes later. It matches ``Fit._elevation_totals``: the sum of the positive
and negative deltas between consecutive records that carry an ``altitude``.
"""

import json

from django.db import migrations
from django.db.models import Q


def _elevation_totals(workout_data):
    """Return ``(gain, loss)`` in metres, or None if the blob is unusable."""
    try:
        data = json.loads(workout_data)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    gain = 0.0
    loss = 0.0
    previous = None
    for record in data.get("record_mesgs") or []:
        altitude = record.get("altitude")
        if altitude is None:
            continue
        try:
            altitude = float(altitude)
        except (TypeError, ValueError):
            continue
        if previous is not None:
            delta = altitude - previous
            if delta > 0:
                gain += delta
            else:
                loss -= delta
        previous = altitude
    return gain, loss


def backfill_elevation(apps, schema_editor):
    Workout = apps.get_model("alors", "Workout")
    workouts = Workout.objects.filter(
        Q(workout_data__isnull=False) & ~Q(workout_data="")
    ).only("id", "workout_data")

    updated = []
    for workout in workouts:
        totals = _elevation_totals(workout.workout_data)
        if totals is None:
            continue
        workout.elevation_gain, workout.elevation_loss = totals
        updated.append(workout)

    if updated:
        Workout.objects.bulk_update(
            updated, ["elevation_gain", "elevation_loss"], batch_size=100
        )


def noop(apps, schema_editor):
    """Nothing to undo here; the fields themselves are dropped by 0007."""


class Migration(migrations.Migration):

    dependencies = [
        ("alors", "0007_workout_elevation_gain_workout_elevation_loss"),
    ]

    operations = [
        migrations.RunPython(backfill_elevation, noop),
    ]
