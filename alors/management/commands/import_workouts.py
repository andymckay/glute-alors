"""Import every Garmin .fit file in a directory as a completed Workout."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from garmin_fit_sdk import Decoder, Stream

from alors.models import WorkoutType, Workout

KM_DECIMAL_PLACES = Decimal("0.01")
User = get_user_model()

SPORT_MAP = {
    "running": WorkoutType.RUN,
    "walking": WorkoutType.WALK,
    "hiking": WorkoutType.HIKE,
    "cycling": WorkoutType.RUN,
    "racing": WorkoutType.RUN,
    "training": WorkoutType.STRENGTH,
}


def _to_datetime(value):
    """Coerce an epoch timestamp (seconds) or a datetime to a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _messages_for(messages, *keys):
    """Return the first message found under any of ``keys``."""
    for key in keys:
        value = messages.get(key)
        if isinstance(value, list) and value:
            return value[0]
        if isinstance(value, dict):
            return value
    return None


class Command(BaseCommand):
    help = (
        "Import every .fit file in a directory as a Workout, storing each "
        "filename in workout_source and all decoded messages in workout_data. "
        "Files whose source is already imported are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "directory",
            type=str,
            help="Directory containing the .fit files to import",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=None,
            help="Set the created_by of each imported workout to this user.",
        )

    def handle(self, *args, **options):
        directory = Path(options["directory"])
        if not directory.is_dir():
            raise CommandError(f"Directory not found: {directory}")

        owner = None
        username = options["username"]
        if username:
            try:
                owner = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"No user with username '{username}'.")

        fit_files = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".fit"
        )
        if not fit_files:
            raise CommandError(f"No .fit files found in {directory}.")

        imported = 0
        skipped = 0
        for fit_path in fit_files:
            source_name = fit_path.name
            if Workout.objects.filter(workout_source=source_name).exists():
                skipped += 1
                self.stdout.write(f"Skipped {source_name} (already imported).")
                continue
            workout = self._import_fit_file(fit_path, owner=owner)
            imported += 1
            self.stdout.write(
                self.style.SUCCESS(f"Imported {workout} from '{source_name}'.")
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done: {imported} imported, {skipped} already present.")
        )

    def _import_fit_file(self, fit_path, owner=None):
        """Decode a single .fit file and return the created Workout."""
        try:
            messages, errors = Decoder(Stream.from_file(str(fit_path))).read()
        except Exception as error:  # noqa: BLE001 - surface as CommandError
            raise CommandError(
                f"Could not read FIT file {fit_path}: {error}"
            ) from error

        if errors:
            raise CommandError(f"Errors while decoding FIT file {fit_path}: {errors}")
        if not messages:
            raise CommandError(f"No messages found in the FIT file {fit_path}.")

        return Workout.objects.create(
            workout_date=self._extract_datetime(messages),
            total_time=self._extract_total_time(messages),
            workout_type=self._extract_type(messages),
            total_distance=self._extract_distance(messages),
            moving_time=self._extract_moving_time(messages),
            pace=self._extract_pace(messages),
            workout_source=fit_path.name,
            workout_data=json.dumps(messages, cls=DjangoJSONEncoder),
            created_by=owner,
        )

    def _extract_datetime(self, messages):
        """Workout datetime from the file_id/record timestamps, else now."""
        file_id = _messages_for(messages, "file_id_mesgs")
        if file_id:
            created = _to_datetime(file_id.get("time_created"))
            if created is not None:
                return created

        records = messages.get("record_mesgs") or []
        for record in records:
            timestamp = _to_datetime(record.get("timestamp"))
            if timestamp is not None:
                return timestamp
        return timezone.now()

    def _extract_total_time(self, messages):
        """Total time from the first and last record timestamps."""
        timestamps = []
        for record in messages.get("record_mesgs") or []:
            timestamp = _to_datetime(record.get("timestamp"))
            if timestamp is not None:
                timestamps.append(timestamp)

        if len(timestamps) >= 2:
            seconds = (max(timestamps) - min(timestamps)).total_seconds()
            return timedelta(seconds=max(0, int(seconds)))
        return timedelta(0)

    def _extract_type(self, messages):
        """Best-effort workout type from the session sport field."""
        session = _messages_for(messages, "session_mesgs")
        if session is not None:
            sport = session.get("sport")
            if isinstance(sport, str):
                if sport.lower() not in SPORT_MAP:
                    raise ValueError("Unknown sport:", sport.lower())
                return SPORT_MAP[sport.lower()]

    def _extract_distance(self, messages):
        """Total distance in km, from the session or the last record message.

        FIT distances are expressed in meters.
        """
        session = _messages_for(messages, "session_mesgs")
        if session is not None:
            meters = session.get("total_distance")
            if meters:
                return (Decimal(str(meters)) / Decimal(1000)).quantize(
                    KM_DECIMAL_PLACES
                )

        cumulative = None
        for record in messages.get("record_mesgs") or []:
            distance = record.get("distance")
            if distance is not None:
                cumulative = distance
        if cumulative:
            return (Decimal(str(cumulative)) / Decimal(1000)).quantize(
                KM_DECIMAL_PLACES
            )
        return None

    def _extract_moving_time(self, messages):
        """Moving time from the session's active timer (in seconds)."""
        session = _messages_for(messages, "session_mesgs")
        if session is not None:
            seconds = session.get("total_timer_time")
            if seconds:
                return timedelta(seconds=int(seconds))
        return None

    def _extract_pace(self, messages):
        """Average pace (time per km), from session speed or distance/time.

        FIT speed is expressed in meters per second, so pace in seconds per
        kilometer is 1000 / speed.
        """
        session = _messages_for(messages, "session_mesgs")
        if session is not None:
            meters_per_second = session.get("avg_speed")
            if meters_per_second:
                seconds_per_km = Decimal(1000) / Decimal(str(meters_per_second))
                return timedelta(seconds=int(seconds_per_km))

        moving_time = self._extract_moving_time(messages)
        distance_km = self._extract_distance(messages)
        seconds = moving_time.total_seconds() if moving_time else 0
        if distance_km and seconds > 0:
            seconds_per_km = Decimal(seconds) / Decimal(str(distance_km))
            return timedelta(seconds=int(seconds_per_km))
        return None
