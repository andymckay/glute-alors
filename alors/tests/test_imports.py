import base64
import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from ..management.commands import import_workouts
from ..management.commands.import_from_intervals import (
    Command as ImportFromIntervalsCommand,
)
from ..management.commands.import_workouts import (
    Command as ImportWorkoutsCommand,
)
from ..models import Workout


class ImportWorkoutsCommandTests(TestCase):
    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 5),
            "total_time": timedelta(minutes=45),
            "workout_type": "run",
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def test_missing_directory_raises_command_error(self):
        with self.assertRaisesMessage(CommandError, "Directory not found"):
            call_command("import_workouts", "/does/not/exist")

    def test_directory_without_fit_files_raises_command_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesMessage(CommandError, "No .fit files found"):
                call_command("import_workouts", directory)

    def test_imports_every_fit_file_in_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")
            Path(directory, "b.fit").write_bytes(b"x")
            Path(directory, "notes.txt").write_text("not a fit file")

            def import_file(fit_path, owner=None):
                return self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory)

        sources = set(Workout.objects.values_list("workout_source", flat=True))
        self.assertEqual(sources, {"a.fit", "b.fit"})

    def test_skips_files_that_are_already_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")
            Path(directory, "b.fit").write_bytes(b"x")
            self.create_workout(workout_source="a.fit")

            imported = []

            def import_file(fit_path, owner=None):
                workout = self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )
                imported.append(fit_path.name)
                return workout

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory)

        self.assertEqual(imported, ["b.fit"])
        sources = set(Workout.objects.values_list("workout_source", flat=True))
        self.assertEqual(sources, {"a.fit", "b.fit"})

    def test_delete_flag_removes_imported_files(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")
            Path(directory, "b.fit").write_bytes(b"x")

            def import_file(fit_path, owner=None):
                return self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory, "--delete")

            remaining = sorted(path.name for path in Path(directory).iterdir())
        self.assertEqual(remaining, [])

    def test_delete_flag_leaves_already_imported_files(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")
            Path(directory, "b.fit").write_bytes(b"x")
            self.create_workout(workout_source="a.fit")

            def import_file(fit_path, owner=None):
                return self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory, "--delete")

            remaining = sorted(path.name for path in Path(directory).iterdir())
        self.assertEqual(remaining, ["a.fit"])

    def test_unknown_username_raises_command_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesMessage(
                CommandError, "No user with username 'ghost'."
            ):
                call_command("import_workouts", directory, "--username", "ghost")

    def test_username_sets_created_by_on_imported_workouts(self):
        owner = User.objects.create_user(username="runner", password="secret123")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")

            def import_file(fit_path, owner=None):
                return self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory, "--username", "runner")

        workout = Workout.objects.get(workout_source="a.fit")
        self.assertEqual(workout.created_by, owner)

    def test_without_username_created_by_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.fit").write_bytes(b"x")

            def import_file(fit_path, owner=None):
                return self.create_workout(
                    workout_source=fit_path.name, created_by=owner
                )

            with mock.patch.object(
                ImportWorkoutsCommand,
                "_import_fit_file",
                side_effect=import_file,
            ):
                call_command("import_workouts", directory)

        workout = Workout.objects.get(workout_source="a.fit")
        self.assertIsNone(workout.created_by)

    def test_import_fit_file_populates_elevation_gain_and_loss(self):
        command = ImportWorkoutsCommand()
        messages = {
            "session_mesgs": [{"sport": "running"}],
            "record_mesgs": [
                {"timestamp": datetime(2026, 9, 4, 8, 0), "altitude": 100},
                {"timestamp": datetime(2026, 9, 4, 8, 5), "altitude": 150},
                {"timestamp": datetime(2026, 9, 4, 8, 10), "altitude": 120},
            ],
        }

        with mock.patch.object(
            import_workouts, "Decoder"
        ) as decoder, mock.patch.object(import_workouts, "Stream"):
            decoder.return_value.read.return_value = (messages, None)
            workout = command._import_fit_file(Path("/tmp/does-not-exist.fit"))

        self.assertEqual(workout.elevation_gain, 50.0)
        self.assertEqual(workout.elevation_loss, 30.0)


@override_settings(INTERVALS_TOKEN="test-intervals-token")
class ImportFromIntervalsCommandTests(TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def activities(self):
        return [
            {"id": "i100000001", "name": "Morning Run"},
            {"id": "i100000002", "name": "Lunch Walk"},
        ]

    def fake_get(self, url, token):
        """Serve an activity listing for list URLs and bytes for files."""
        if "/activities?" in url:
            return 200, json.dumps(self.activities()).encode("utf-8")
        return 200, b"FIT-CONTENT"

    @override_settings(INTERVALS_TOKEN=None)
    def test_requires_api_key(self):
        with self.assertRaisesMessage(CommandError, "INTERVALS_TOKEN"):
            call_command("import_from_intervals", "--data-dir", self.data_dir)

    def test_downloads_original_files_for_latest_activities(self):
        with mock.patch.object(
            ImportFromIntervalsCommand, "_get", side_effect=self.fake_get
        ):
            call_command("import_from_intervals", "--data-dir", self.data_dir)

        first = Path(self.data_dir) / "i100000001.fit"
        second = Path(self.data_dir) / "i100000002.fit"
        self.assertEqual(first.read_bytes(), b"FIT-CONTENT")
        self.assertEqual(second.read_bytes(), b"FIT-CONTENT")

    def test_skips_existing_files_unless_force(self):
        existing = Path(self.data_dir) / "i100000001.fit"
        existing.write_bytes(b"OLD-CONTENT")

        with mock.patch.object(
            ImportFromIntervalsCommand, "_get", side_effect=self.fake_get
        ):
            call_command("import_from_intervals", "--data-dir", self.data_dir)
        self.assertEqual(existing.read_bytes(), b"OLD-CONTENT")

        with mock.patch.object(
            ImportFromIntervalsCommand, "_get", side_effect=self.fake_get
        ):
            call_command(
                "import_from_intervals",
                "--data-dir",
                self.data_dir,
                "--force",
            )
        self.assertEqual(existing.read_bytes(), b"FIT-CONTENT")

    def test_skips_activity_without_original_file(self):
        def no_file_get(url, token):
            if "/activities?" in url:
                return 200, json.dumps(self.activities()).encode("utf-8")
            return 400, b"no original file"

        with mock.patch.object(
            ImportFromIntervalsCommand, "_get", side_effect=no_file_get
        ):
            call_command("import_from_intervals", "--data-dir", self.data_dir)

        first = Path(self.data_dir) / "i100000001.fit"
        second = Path(self.data_dir) / "i100000002.fit"
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_auth_headers_use_basic_auth_with_api_key_username(self):
        command = ImportFromIntervalsCommand()
        headers = command._auth_headers("secret-token")
        expected = "Basic " + base64.b64encode(b"API_KEY:secret-token").decode("ascii")
        self.assertEqual(headers["Authorization"], expected)
        self.assertIn("Mozilla", headers["User-Agent"])
