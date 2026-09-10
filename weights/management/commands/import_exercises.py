"""Import the gym exercise catalogue into the Exercise model.

Reads every ``exercise.json`` from the per-exercise folders under
``weights/exercises/`` (the same layout as the source ``exercises.json``
dataset) and upserts them into the database keyed by ``name``.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from weights.models import Exercise

# weights/ (where this command and the data live)
APP_DIR = Path(__file__).resolve().parents[2]
EXERCISES_DIR = APP_DIR / "exercises"


class Command(BaseCommand):
    help = "Populate the Exercise model from weights/exercises/**/exercise.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            default=str(EXERCISES_DIR),
            help="Folder containing per-exercise subfolders with exercise.json "
            "(default: weights/exercises).",
        )

    def handle(self, *args, **options):
        source = Path(options["directory"])
        if not source.is_dir():
            raise CommandError(f"Exercises directory not found: {source}")

        created = 0
        updated = 0
        skipped = []

        with transaction.atomic():
            for folder in sorted(p for p in source.iterdir() if p.is_dir()):
                json_path = folder / "exercise.json"
                if not json_path.exists():
                    skipped.append(f"{folder.name}: no exercise.json")
                    continue
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    skipped.append(f"{folder.name}: {exc}")
                    continue

                defaults = {
                    "force": data.get("force"),
                    "level": data.get("level"),
                    "mechanic": data.get("mechanic"),
                    "equipment": data.get("equipment"),
                    "primary_muscles": data.get("primaryMuscles", []),
                    "secondary_muscles": data.get("secondaryMuscles", []),
                    "instructions": data.get("instructions", []),
                    "category": data.get("category"),
                }
                _, was_created = Exercise.objects.update_or_create(
                    name=data.get("name") or folder.name,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        for item in skipped:
            self.stderr.write(self.style.WARNING(f"Skipped {item}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated, "
                f"{len(skipped)} skipped."
            )
        )
