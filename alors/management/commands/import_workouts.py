"""Import every Garmin .fit file in a directory as a completed Workout."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from garmin_fit_sdk import Decoder, Stream

from alors.models import Workout
from parsers.fit import Fit

User = get_user_model()


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
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete each .fit file after it has been successfully imported.",
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
            if options["delete"]:
                fit_path.unlink()
                self.stdout.write(self.style.SUCCESS(f"Deleted {source_name}."))

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

        fit = Fit(messages)
        return Workout.objects.create(
            workout_date=fit.get_datetime(),
            total_time=fit.get_total_time(),
            workout_type=fit.get_workout_type(),
            total_distance=fit.get_distance(),
            moving_time=fit.get_moving_time(),
            pace=fit.get_pace(),
            elevation_gain=fit.elevation_gain(),
            elevation_loss=fit.elevation_loss(),
            workout_source=fit_path.name,
            workout_data=json.dumps(messages, cls=DjangoJSONEncoder),
            created_by=owner,
        )
