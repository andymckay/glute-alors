import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ..models import Issue, Workout


class WorkoutModelTests(SimpleTestCase):
    def make_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 5),
            "total_time": timedelta(minutes=45),
            "workout_type": "run",
        }
        values.update(overrides)
        return Workout(**values)

    def test_required_fields_are_valid(self):
        workout = self.make_workout()
        workout.full_clean()  # should not raise

    def test_all_optional_fields_may_be_empty(self):
        workout = self.make_workout(
            total_distance=None,
            moving_time=None,
            effort=None,
            feeling=None,
            notes="",
        )
        workout.full_clean()  # should not raise

    def test_effort_above_scale_is_rejected(self):
        workout = self.make_workout(effort=11)
        with self.assertRaises(ValidationError) as context:
            workout.full_clean()
        self.assertIn("effort", context.exception.message_dict)

    def test_effort_below_scale_is_rejected(self):
        workout = self.make_workout(effort=0)
        with self.assertRaises(ValidationError) as context:
            workout.full_clean()
        self.assertIn("effort", context.exception.message_dict)

    def test_feeling_above_scale_is_rejected(self):
        workout = self.make_workout(feeling=6)
        with self.assertRaises(ValidationError) as context:
            workout.full_clean()
        self.assertIn("feeling", context.exception.message_dict)

    def test_feeling_below_scale_is_rejected(self):
        workout = self.make_workout(feeling=0)
        with self.assertRaises(ValidationError) as context:
            workout.full_clean()
        self.assertIn("feeling", context.exception.message_dict)

    def test_valid_effort_and_feeling_pass(self):
        workout = self.make_workout(effort=7, feeling=4)
        workout.full_clean()  # should not raise


class WorkoutDetailViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 5, 8, 30),
            total_time=timedelta(hours=1, minutes=2, seconds=3),
            workout_type="run",
            total_distance=10.5,
            moving_time=timedelta(minutes=58),
            effort=7,
            feeling=4,
            notes="Felt **good**.",
        )

    def test_detail_shows_workout_fields(self):
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        for text in [
            "Run",
            "Sept. 5, 2026",
            "1:02:03",
            "10.50 km",
            "0:58:00",
            "Hard",
            "Good",
        ]:
            self.assertContains(response, text)

    def test_detail_renders_notes_as_markdown(self):
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<strong>good</strong>")


class WorkoutEditViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 5, 8, 30),
            total_time=timedelta(hours=1),
            workout_type="run",
            total_distance=10.5,
            moving_time=timedelta(minutes=58),
            effort=7,
            feeling=4,
            notes="Felt **good**.",
        )
        self.url = reverse("alors:workout_edit", args=[self.workout.pk])

    def test_form_only_exposes_log_fields_and_issues(self):
        from ..forms import WorkoutEditForm

        self.assertEqual(
            list(WorkoutEditForm().fields.keys()),
            ["notes", "effort", "feeling", "issues"],
        )

    def test_edit_page_shows_current_values(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Felt **good**.")
        self.assertContains(response, 'value="7"')
        self.assertContains(response, 'value="4"')

    def test_effort_and_feeling_use_select_widgets(self):
        from ..forms import WorkoutEditForm

        form = WorkoutEditForm()
        self.assertEqual(form.fields["effort"].widget.input_type, "select")
        self.assertEqual(form.fields["feeling"].widget.input_type, "select")
        self.assertEqual(
            [value for value, _ in form.fields["effort"].choices if value != ""],
            [str(n) for n in range(1, 11)],
        )
        self.assertEqual(
            [value for value, _ in form.fields["feeling"].choices if value != ""],
            [str(n) for n in range(1, 6)],
        )

    def test_edit_updates_only_allowed_fields(self):
        response = self.client.post(
            self.url,
            {
                "notes": "Now **better**.",
                "effort": "8",
                "feeling": "5",
            },
        )
        self.assertRedirects(
            response,
            reverse("alors:workout_detail", args=[self.workout.pk]),
        )
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.notes, "Now **better**.")
        self.assertEqual(self.workout.effort, 8)
        self.assertEqual(self.workout.feeling, 5)
        # Everything else must remain untouched.
        self.assertEqual(
            self.workout.workout_date,
            datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(self.workout.workout_type, "run")
        self.assertEqual(self.workout.total_time, timedelta(hours=1))
        self.assertEqual(self.workout.total_distance, Decimal("10.5"))
        self.assertEqual(self.workout.moving_time, timedelta(minutes=58))

    def test_edit_can_clear_optional_fields(self):
        response = self.client.post(
            self.url,
            {"notes": "", "effort": "", "feeling": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.notes, "")
        self.assertIsNone(self.workout.effort)
        self.assertIsNone(self.workout.feeling)

    def test_edit_rejects_effort_out_of_range(self):
        response = self.client.post(
            self.url,
            {"notes": "note", "effort": "11", "feeling": "4"},
        )
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.effort, 7)  # unchanged

    def test_edit_attaches_multiple_issues(self):
        first = Issue.objects.create(title="First")
        second = Issue.objects.create(title="Second")
        response = self.client.post(
            self.url,
            {
                "notes": "note",
                "effort": "7",
                "feeling": "4",
                "issues": [str(first.pk), str(second.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.workout.refresh_from_db()
        self.assertCountEqual(
            list(self.workout.issues.values_list("id", flat=True)),
            [first.pk, second.pk],
        )

    def test_edit_does_not_change_linked_issue_content(self):
        issue = Issue.objects.create(title="Old title")
        self.workout.issues.add(issue)
        response = self.client.post(
            self.url,
            {
                "notes": "note",
                "effort": "7",
                "feeling": "4",
                "issues": [str(issue.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        issue.refresh_from_db()
        self.assertEqual(issue.title, "Old title")
        self.assertTrue(self.workout.issues.filter(pk=issue.pk).exists())

    def test_detail_shows_linked_issues(self):
        issue = Issue.objects.create(title="Crash")
        self.workout.issues.add(issue)
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crash")


class WorkoutSourceDataTests(TestCase):
    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 5),
            "total_time": timedelta(minutes=45),
            "workout_type": "run",
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def test_defaults(self):
        workout = self.create_workout()
        workout.refresh_from_db()
        self.assertIsNone(workout.workout_source)
        self.assertEqual(workout.source_url, "")
        self.assertEqual(workout.workout_data, "")

    def test_stores_source_url_source_and_data(self):
        data = {"strava_id": 12345, "segments": [1, 2, 3]}
        workout = self.create_workout(
            workout_source="strava",
            source_url="https://example.com/workout/1",
            workout_data=json.dumps(data),
        )
        workout.refresh_from_db()
        self.assertEqual(workout.workout_source, "strava")
        self.assertEqual(workout.source_url, "https://example.com/workout/1")
        self.assertEqual(workout.workout_data, json.dumps(data))
