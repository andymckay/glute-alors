"""Rebuild every weekly summary from the current planned and completed workouts.

``WeeklySummary`` rows are normally maintained by signals, but they can drift
out of sync (for example when data was imported before the signals existed, or
when rows were edited directly).  This command wipes the summaries for the
requested range and regenerates them from scratch using the same aggregation
as the signals.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_date

from alors.models import PlannedWorkout, WeeklySummary, Workout
from alors.signals import _sunday_for, refresh_weekly_summary


def _as_local_date(value):
    """Return the local date for a date or aware datetime."""
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


class Command(BaseCommand):
    help = "Delete and regenerate weekly summaries from the stored workouts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            help="Only rebuild weeks on or after this date (YYYY-MM-DD). "
            "Defaults to the earliest planned/completed workout.",
        )
        parser.add_argument(
            "--end",
            help="Only rebuild weeks on or before this date (YYYY-MM-DD). "
            "Defaults to the latest planned/completed workout.",
        )

    def handle(self, *args, **options):
        start = self._parse_date_option("--start", options.get("start"))
        end = self._parse_date_option("--end", options.get("end"))

        first_date, last_date = self._date_bounds()
        if start is not None:
            first_date = start
        if end is not None:
            last_date = end

        if first_date is None or last_date is None:
            self.stdout.write("No planned or completed workouts found; nothing to do.")
            return
        if first_date > last_date:
            raise CommandError("The start date must not be after the end date.")

        first_sunday = _sunday_for(first_date)
        last_sunday = _sunday_for(last_date)

        deleted, _ = WeeklySummary.objects.filter(
            date__gte=first_sunday, date__lte=last_sunday
        ).delete()

        sunday = first_sunday
        while sunday <= last_sunday:
            refresh_weekly_summary(sunday)
            sunday += datetime.timedelta(days=7)

        recreated = WeeklySummary.objects.filter(
            date__gte=first_sunday, date__lte=last_sunday
        ).count()
        noun = "summary" if recreated == 1 else "summaries"
        self.stdout.write(
            self.style.SUCCESS(
                f"Recreated {recreated} weekly {noun} between "
                f"{first_sunday} and {last_sunday} (deleted {deleted})."
            )
        )

    def _parse_date_option(self, name, value):
        if value is None:
            return None
        parsed = parse_date(value)
        if parsed is None:
            raise CommandError(f"{name} must be a valid date in YYYY-MM-DD format.")
        return parsed

    def _date_bounds(self):
        """Return the earliest and latest workout dates across both models."""
        planned = PlannedWorkout.objects.aggregate(
            first=Min("workout_date"), last=Max("workout_date")
        )
        completed = Workout.objects.aggregate(
            first=Min("workout_date"), last=Max("workout_date")
        )

        dates = []
        if planned["first"] is not None:
            dates.extend([planned["first"], planned["last"]])
        if completed["first"] is not None:
            dates.extend(
                [
                    _as_local_date(completed["first"]),
                    _as_local_date(completed["last"]),
                ]
            )
        if not dates:
            return None, None
        return min(dates), max(dates)
