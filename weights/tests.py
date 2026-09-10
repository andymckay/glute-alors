import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Exercise


class ExerciseModelTests(TestCase):
    def test_str_and_list_fields(self):
        exercise = Exercise.objects.create(
            name="Test Curl",
            level=Exercise._meta.get_field("level").choices[0][0],
            category="strength",
            force="pull",
            mechanic="isolation",
            equipment="dumbbell",
            primary_muscles=["biceps"],
            secondary_muscles=["forearms"],
            instructions=["Curl the bar.", "Lower slowly."],
        )
        self.assertEqual(str(exercise), "Test Curl")
        self.assertEqual(list(exercise.primary_muscles), ["biceps"])
        self.assertEqual(len(exercise.instructions), 2)


class ImportExercisesCommandTests(TestCase):
    def test_imports_and_upserts_from_json(self):
        payload = {
            "name": "Test Curl",
            "force": "pull",
            "level": "beginner",
            "mechanic": "isolation",
            "equipment": "dumbbell",
            "primaryMuscles": ["biceps"],
            "secondaryMuscles": [],
            "instructions": ["Curl the bar."],
            "category": "strength",
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Test_Curl"
            folder.mkdir()
            (folder / "exercise.json").write_text(json.dumps(payload))

            call_command("import_exercises", directory=tmp)
            self.assertEqual(Exercise.objects.count(), 1)
            exercise = Exercise.objects.get(name="Test Curl")
            self.assertEqual(exercise.equipment, "dumbbell")
            self.assertEqual(list(exercise.primary_muscles), ["biceps"])

            # Re-running updates the existing row rather than duplicating it.
            payload["equipment"] = "barbell"
            (folder / "exercise.json").write_text(json.dumps(payload))
            call_command("import_exercises", directory=tmp)
            self.assertEqual(Exercise.objects.count(), 1)
            exercise.refresh_from_db()
            self.assertEqual(exercise.equipment, "barbell")
