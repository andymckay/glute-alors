import base64
import json
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from icalendar import Calendar

from .ical import render_calendar
from .management.commands.import_from_intervals import (
    Command as ImportFromIntervalsCommand,
)
from .management.commands.import_workouts import (
    Command as ImportWorkoutsCommand,
)
from .models import (
    Comment,
    Issue,
    Label,
    Notification,
    PlannedWorkout,
    UserProfile,
    WarmUp,
    WeeklySummary,
    Workout,
    WorkoutType,
)
from .validators import validate_date


class ValidateDateTests(SimpleTestCase):
    def test_valid_iso_dates_do_not_raise(self):
        for date in ["2026-01-01", "2026-09-02", "2026-12-31", "2028-02-29"]:
            with self.subTest(date=date):
                # Should not raise an exception.
                validate_date(date)

    def test_invalid_dates_raise_validation_error(self):
        for date in ["2026-02-30", "2026-13-01", "not-a-date", "2026/09/02", ""]:
            with self.subTest(date=date):
                with self.assertRaises(ValidationError):
                    validate_date(date)

    def test_error_message_names_the_bad_date(self):
        with self.assertRaisesMessage(
            ValidationError, "2026-02-30 is not a valid date"
        ):
            validate_date("2026-02-30")


class LoggedOutViewTests(TestCase):
    """Workout views must not be usable by a logged-out user.

    Every @login_required view should respond with a redirect to the
    login page (carrying the requested URL as the ``next`` parameter)
    when the user is not authenticated.
    """

    def setUp(self):
        self.workout = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-02",
            total_distance="10.00",
        )

    def assert_login_required(self, method, url):
        response = getattr(self.client, method)(url)
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        self.assertEqual(parsed.path, "/", "should redirect to the login page")
        self.assertEqual(parse_qs(parsed.query).get("next"), [url])

    def test_logout_requires_login(self):
        url = reverse("alors:logout")
        self.assert_login_required("get", url)

    def test_profile_requires_login(self):
        url = reverse("alors:profile")
        self.assert_login_required("get", url)

    def test_notifications_requires_login(self):
        url = reverse("alors:notifications")
        self.assert_login_required("get", url)

    def test_mark_all_notifications_read_requires_login(self):
        url = reverse("alors:mark_all_notifications_read")
        self.assert_login_required("post", url)

    def test_calendar_requires_login(self):
        url = reverse("alors:calendar")
        self.assert_login_required("get", url)

    def test_add_planned_workout_requires_login(self):
        url = reverse("alors:add_planned")
        self.assert_login_required("get", url)

    def test_planned_workout_detail_requires_login(self):
        url = reverse("alors:planned_detail", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_edit_planned_workout_requires_login(self):
        url = reverse("alors:edit_planned", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_delete_planned_workout_requires_login(self):
        url = reverse("alors:delete_planned", args=[self.workout.pk])
        self.assert_login_required("post", url)

    def test_workout_is_not_deleted_by_anonymous_delete(self):
        """An anonymous POST to delete must not delete the workout."""
        url = reverse("alors:delete_planned", args=[self.workout.pk])
        self.assert_login_required("post", url)
        self.assertTrue(PlannedWorkout.objects.filter(pk=self.workout.pk).exists())

    def test_planned_workout_webcal_is_publicly_available(self):
        # The ICS feed is intentionally public so calendar apps can subscribe.
        response = self.client.get(reverse("alors:planned_webcal"))
        self.assertEqual(response.status_code, 200)

    def test_warmup_list_requires_login(self):
        url = reverse("alors:warmup_list")
        self.assert_login_required("get", url)

    def test_warmup_add_requires_login(self):
        url = reverse("alors:warmup_add")
        self.assert_login_required("get", url)

    def test_warmup_edit_requires_login(self):
        url = reverse("alors:warmup_edit", args=[1])
        self.assert_login_required("get", url)

    def test_warmup_delete_requires_login(self):
        url = reverse("alors:warmup_delete", args=[1])
        self.assert_login_required("post", url)

    def test_workout_detail_requires_login(self):
        url = reverse("alors:workout_detail", args=[1])
        self.assert_login_required("get", url)

    def test_workout_edit_requires_login(self):
        url = reverse("alors:workout_edit", args=[1])
        self.assert_login_required("get", url)

    def test_issue_list_requires_login(self):
        url = reverse("alors:issue_list")
        self.assert_login_required("get", url)

    def test_issue_add_requires_login(self):
        url = reverse("alors:issue_add")
        self.assert_login_required("get", url)

    def test_issue_edit_requires_login(self):
        url = reverse("alors:issue_edit", args=[1])
        self.assert_login_required("get", url)

    def test_issue_delete_requires_login(self):
        url = reverse("alors:issue_delete", args=[1])
        self.assert_login_required("post", url)

    def test_label_list_requires_login(self):
        url = reverse("alors:label_list")
        self.assert_login_required("get", url)

    def test_label_add_requires_login(self):
        url = reverse("alors:label_add")
        self.assert_login_required("get", url)

    def test_label_edit_requires_login(self):
        url = reverse("alors:label_edit", args=[1])
        self.assert_login_required("get", url)

    def test_label_delete_requires_login(self):
        url = reverse("alors:label_delete", args=[1])
        self.assert_login_required("post", url)

    def test_add_planned_comment_requires_login(self):
        url = reverse("alors:add_planned_comment", args=[1])
        self.assert_login_required("post", url)

    def test_add_workout_comment_requires_login(self):
        url = reverse("alors:add_workout_comment", args=[1])
        self.assert_login_required("post", url)


class IcalGeneratorTests(SimpleTestCase):
    def test_render_calendar_with_no_workouts(self):
        doc = render_calendar([])
        self.assertIn("BEGIN:VCALENDAR", doc)
        self.assertIn("END:VCALENDAR", doc)
        self.assertNotIn("BEGIN:VEVENT", doc)

    def test_output_parses_with_icalendar_library(self):
        calendar = Calendar.from_ical(render_calendar([]))
        self.assertEqual(calendar.name, "VCALENDAR")
        self.assertEqual(calendar.get("version"), "2.0")


class WebCalFeedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="Easy 2 km jog",
            created_by=self.user,
        )
        self.workout = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-02",
            total_distance="10.50",
            warm_up=self.warmup,
            notes="Keep it steady",
        )

    def feed_calendar(self):
        response = self.client.get(reverse("alors:planned_webcal"))
        self.assertEqual(response.status_code, 200)
        return Calendar.from_ical(response.content)

    def test_feed_returns_icalendar_content_type(self):
        response = self.client.get(reverse("alors:planned_webcal"))
        self.assertTrue(response["Content-Type"].startswith("text/calendar"))

    def test_feed_sets_download_filename(self):
        response = self.client.get(reverse("alors:planned_webcal"))
        self.assertIn("planned-workouts.ics", response["Content-Disposition"])

    def test_feed_is_available_without_login(self):
        self.client.logout()
        calendar = self.feed_calendar()  # asserts a 200 and parses the feed
        events = list(calendar.walk("VEVENT"))
        self.assertEqual(len(events), 1)

    def test_feed_contains_a_vevent_for_each_workout(self):
        calendar = self.feed_calendar()
        events = list(calendar.walk("VEVENT"))
        self.assertEqual(len(events), 1)

    def test_vevent_has_expected_details(self):
        calendar = self.feed_calendar()
        (event,) = calendar.walk("VEVENT")
        self.assertEqual(
            event.get("uid"), f"planned-workout-{self.workout.pk}@glute-alors"
        )
        self.assertEqual(event.get("summary"), "Run workout")
        self.assertEqual(event.get("dtstart").dt, date(2026, 9, 2))
        self.assertIn("10.50 km planned", event.get("description"))
        self.assertIn("Easy 2 km jog", event.get("description"))
        self.assertIn("Keep it steady", event.get("description"))

    def test_feed_orders_workouts_by_date(self):
        PlannedWorkout.objects.create(
            workout_type=WorkoutType.WALK,
            workout_date="2026-09-01",
            total_distance="3.00",
        )
        calendar = self.feed_calendar()
        start_dates = [event.get("dtstart").dt for event in calendar.walk("VEVENT")]
        self.assertEqual(start_dates, sorted(start_dates))
        self.assertEqual(start_dates[0], date(2026, 9, 1))
        self.assertEqual(start_dates[1], date(2026, 9, 2))


class AddPlannedWorkoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="Jog slowly.",
            created_by=self.user,
        )

    def add_workout(self):
        return self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "21.10",
            },
        )

    def test_add_sets_created_by_to_logged_in_user(self):
        response = self.add_workout()
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertEqual(workout.created_by, self.user)

    def test_add_can_link_a_warmup_instance(self):
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "21.10",
                "warm_up": self.warmup.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertEqual(workout.warm_up, self.warmup)

    def test_warm_up_field_is_optional_with_empty_label(self):
        from .forms import PlannedWorkoutForm

        field = PlannedWorkoutForm().fields["warm_up"]
        self.assertFalse(field.required)
        self.assertEqual(field.empty_label, "No warm-up")

    def test_distance_field_is_optional_in_form(self):
        from .forms import PlannedWorkoutForm

        self.assertFalse(PlannedWorkoutForm().fields["total_distance"].required)

    def test_distance_is_optional_when_adding(self):
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Recovery",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-06",
            },
        )
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertIsNone(workout.total_distance)

    def test_created_by_is_not_an_editable_form_field(self):
        from .forms import PlannedWorkoutForm

        self.assertNotIn("created_by", PlannedWorkoutForm().fields)

    def test_user_related_name_links_back_to_workouts(self):
        self.add_workout()
        self.assertEqual(self.user.planned_workouts.count(), 1)
        self.assertEqual(
            self.user.planned_workouts.get().title,
            "Long run",
        )


class WarmUpViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="Jog slowly for five minutes.",
            created_by=self.user,
        )

    def test_list_shows_warmups(self):
        response = self.client.get(reverse("alors:warmup_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Easy jog")
        self.assertContains(response, reverse("alors:warmup_add"))

    def test_add_sets_created_by_and_redirects(self):
        response = self.client.post(
            reverse("alors:warmup_add"),
            {"title": "Strides", "text": "Six short strides."},
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        warmup = WarmUp.objects.get(title="Strides")
        self.assertEqual(warmup.created_by, self.user)

    def test_edit_updates_warmup(self):
        url = reverse("alors:warmup_edit", args=[self.warmup.pk])
        response = self.client.post(
            url,
            {"title": "Easy jog & drills", "text": "Updated routine."},
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        self.warmup.refresh_from_db()
        self.assertEqual(self.warmup.title, "Easy jog & drills")
        self.assertEqual(self.warmup.text, "Updated routine.")

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:warmup_edit", args=[self.warmup.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.warmup.title)

    def test_delete_removes_warmup(self):
        response = self.client.post(
            reverse("alors:warmup_delete", args=[self.warmup.pk])
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        self.assertFalse(WarmUp.objects.filter(pk=self.warmup.pk).exists())


class MarkdownFilterTests(SimpleTestCase):
    def render(self, value):
        template = Template("{% load markdown_extras %}{{ value|markdown }}")
        return template.render(Context({"value": value}))

    def test_renders_headings(self):
        self.assertIn("<h1>Heading</h1>", self.render("# Heading"))

    def test_renders_emphasis(self):
        self.assertIn("<strong>bold</strong>", self.render("**bold**"))

    def test_empty_value_renders_nothing(self):
        self.assertEqual(self.render(""), "")

    def test_output_is_marked_safe(self):
        template = Template("{% load markdown_extras %}{{ value|markdown }}")
        output = template.render(Context({"value": "**bold**"}))
        self.assertNotIn("&lt;strong&gt;", output)


class WorkoutDetailMarkdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="# Warm up heading\n\nSome **instructions**.",
            created_by=self.user,
        )
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            warm_up=self.warmup,
            notes="# Notes\n\nRuns with **pace**.",
        )

    def test_detail_renders_warmup_text_as_markdown(self):
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Warm up heading</h1>")
        self.assertContains(response, "<strong>instructions</strong>")

    def test_detail_renders_notes_as_markdown(self):
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Notes</h1>")
        self.assertContains(response, "<strong>pace</strong>")


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
        from .forms import WorkoutEditForm

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
        from .forms import WorkoutEditForm

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
        first = Issue.objects.create(title="First", text="One")
        second = Issue.objects.create(title="Second", text="Two")
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
        issue = Issue.objects.create(title="Old title", text="Old **text**.")
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
        self.assertEqual(issue.text, "Old **text**.")
        self.assertTrue(self.workout.issues.filter(pk=issue.pk).exists())

    def test_detail_shows_linked_issues(self):
        issue = Issue.objects.create(title="Crash", text="It **broke**.")
        self.workout.issues.add(issue)
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crash")
        self.assertContains(response, "<strong>broke</strong>")


class IssueViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.issue = Issue.objects.create(
            title="App crashes",
            text="It breaks **badly** on #launch.",
        )

    def test_list_shows_issues(self):
        response = self.client.get(reverse("alors:issue_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "App crashes")
        self.assertContains(response, reverse("alors:issue_add"))

    def test_list_renders_issue_text_as_markdown(self):
        response = self.client.get(reverse("alors:issue_list"))
        self.assertContains(response, "<strong>badly</strong>")

    def test_add_creates_issue_and_redirects(self):
        response = self.client.post(
            reverse("alors:issue_add"),
            {"title": "New bug", "text": "Something **breaks**."},
        )
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.assertTrue(Issue.objects.filter(title="New bug").exists())

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:issue_edit", args=[self.issue.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "App crashes")

    def test_edit_updates_issue(self):
        url = reverse("alors:issue_edit", args=[self.issue.pk])
        response = self.client.post(
            url,
            {"title": "App crashes on login", "text": "Fixed wording."},
        )
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.title, "App crashes on login")
        self.assertEqual(self.issue.text, "Fixed wording.")

    def test_delete_removes_issue(self):
        response = self.client.post(reverse("alors:issue_delete", args=[self.issue.pk]))
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.assertFalse(Issue.objects.filter(pk=self.issue.pk).exists())

    def test_add_sets_created_by_to_logged_in_user(self):
        response = self.client.post(
            reverse("alors:issue_add"),
            {"title": "New bug", "text": "Something **breaks**."},
        )
        self.assertEqual(response.status_code, 302)
        issue = Issue.objects.get(title="New bug")
        self.assertEqual(issue.created_by, self.user)

    def test_created_by_is_not_an_editable_field(self):
        from .forms import IssueForm

        self.assertEqual(list(IssueForm().fields.keys()), ["title", "text"])

    def test_timestamps_are_set_and_updated(self):
        self.issue.refresh_from_db()
        self.assertIsNotNone(self.issue.created_at)
        self.assertIsNotNone(self.issue.updated_at)
        created_before = self.issue.created_at
        updated_before = self.issue.updated_at

        self.issue.text = "Edited text."
        self.issue.save()
        self.issue.refresh_from_db()
        self.assertGreaterEqual(self.issue.updated_at, updated_before)
        self.assertEqual(self.issue.created_at, created_before)


class WeeklySummaryModelTests(TestCase):
    def test_can_store_nested_json_summary(self):
        data = {
            "total_distance_km": 42.5,
            "workouts": 5,
            "issues": ["Sore knee"],
        }
        summary = WeeklySummary.objects.create(
            date=date(2026, 9, 7),
            summary=data,
        )
        summary.refresh_from_db()
        self.assertEqual(summary.date, date(2026, 9, 7))
        self.assertEqual(summary.summary, data)

    def test_summary_defaults_to_empty_dict(self):
        summary = WeeklySummary.objects.create(date=date(2026, 9, 7))
        self.assertEqual(summary.summary, {})

    def test_can_store_a_list(self):
        summary = WeeklySummary.objects.create(
            date=date(2026, 9, 7),
            summary=["ran", "swam"],
        )
        summary.refresh_from_db()
        self.assertEqual(summary.summary, ["ran", "swam"])


class WeeklySummarySignalTests(TestCase):
    def create_planned(self, workout_date, distance="10.00", workout_type="run"):
        return PlannedWorkout.objects.create(
            workout_type=workout_type,
            workout_date=workout_date,
            total_distance=distance,
        )

    def create_workout_record(self, workout_date, distance="10.00", workout_type="run"):
        if isinstance(workout_date, date) and not isinstance(workout_date, datetime):
            workout_date = datetime.combine(workout_date, datetime.min.time())
        return Workout.objects.create(
            workout_date=workout_date,
            total_time=timedelta(minutes=30),
            workout_type=workout_type,
            total_distance=distance,
        )

    def summary_for(self, sunday):
        return WeeklySummary.objects.get(date=sunday)

    def test_planned_workout_summarised_by_type(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # Wednesday
        summary = self.summary_for(date(2026, 9, 6))  # that week's Sunday
        self.assertEqual(
            summary.summary,
            {
                "planned_workout": {
                    "run": {
                        "workouts": 1,
                        "total_distance": 10.0,
                        "total_time": 0,
                    }
                },
                "workout": {},
            },
        )

    def test_planned_types_are_grouped(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # Wed
        self.create_planned(date(2026, 9, 4), distance="3.00", workout_type="walk")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["planned_workout"],
            {
                "run": {
                    "workouts": 1,
                    "total_distance": 10.0,
                    "total_time": 0,
                },
                "walk": {
                    "workouts": 1,
                    "total_distance": 3.0,
                    "total_time": 0,
                },
            },
        )

    def test_workout_summarised_by_type_with_time(self):
        self.create_workout_record(date(2026, 9, 2), distance="10.00")
        self.create_workout_record(date(2026, 9, 4), distance="5.00")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["workout"],
            {
                "run": {
                    "workouts": 2,
                    "total_distance": 15.0,
                    "total_time": 3600,  # 2 x 30 minutes
                }
            },
        )

    def test_planned_and_workout_kept_separate(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # planned run
        self.create_workout_record(
            date(2026, 9, 4), distance="5.00", workout_type="run"
        )
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["planned_workout"]["run"]["total_distance"], 10.0
        )
        self.assertEqual(summary.summary["workout"]["run"]["total_distance"], 5.0)
        self.assertEqual(summary.summary["workout"]["run"]["total_time"], 1800)

    def test_non_run_workout_does_not_update_weekly_summary(self):
        self.create_workout_record(date(2026, 9, 2), workout_type="walk")
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())

    def test_updating_workout_record_refreshes_summary(self):
        record = self.create_workout_record(date(2026, 9, 2), distance="10.00")
        record.total_distance = "15.00"
        record.save()
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["workout"]["run"]["total_distance"], 15.0)

    def test_moving_workout_record_updates_both_weeks(self):
        record = self.create_workout_record(date(2026, 9, 2))  # week ending 09-06
        record.workout_date = datetime(2026, 9, 10, 8, 0)  # week ending 09-13
        record.save()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        summary = self.summary_for(date(2026, 9, 13))
        self.assertEqual(summary.summary["workout"]["run"]["workouts"], 1)

    def test_deleting_workout_record_removes_weekly_summary(self):
        record = self.create_workout_record(date(2026, 9, 2))
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        record.delete()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())

    def test_model_helpers_sum_the_new_structure(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")
        self.create_planned(date(2026, 9, 4), distance="3.00", workout_type="walk")
        self.create_workout_record(date(2026, 9, 2), distance="5.00")
        summary = self.summary_for(date(2026, 9, 6)).summary
        self.assertEqual(summary["planned_workout"]["run"]["workouts"], 1)
        self.assertEqual(summary["planned_workout"]["walk"]["workouts"], 1)
        self.assertEqual(summary["planned_workout"]["run"]["total_distance"], 10.0)
        self.assertEqual(summary["workout"]["run"]["workouts"], 1)
        self.assertEqual(summary["workout"]["run"]["total_distance"], 5.0)


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

    def test_extract_datetime_from_file_id(self):
        command = ImportWorkoutsCommand()
        messages = {"file_id_mesgs": [{"time_created": datetime(2026, 9, 3, 12, 0)}]}
        self.assertEqual(
            command._extract_datetime(messages),
            datetime(2026, 9, 3, 12, 0),
        )

    def test_extract_datetime_falls_back_to_record(self):
        command = ImportWorkoutsCommand()
        messages = {"record_mesgs": [{"timestamp": datetime(2026, 9, 4, 8, 0)}]}
        self.assertEqual(
            command._extract_datetime(messages),
            datetime(2026, 9, 4, 8, 0),
        )

    def test_extract_total_time_from_records(self):
        command = ImportWorkoutsCommand()
        messages = {
            "record_mesgs": [
                {"timestamp": datetime(2026, 9, 4, 8, 0)},
                {"timestamp": datetime(2026, 9, 4, 8, 45)},
            ]
        }
        self.assertEqual(
            command._extract_total_time(messages),
            timedelta(minutes=45),
        )

    def test_extract_type_maps_sport(self):
        command = ImportWorkoutsCommand()
        messages = {"session_mesgs": [{"sport": "walking"}]}
        self.assertEqual(command._extract_type(messages), "walk")

    def test_extract_type_returns_none_without_session(self):
        command = ImportWorkoutsCommand()
        self.assertIsNone(command._extract_type({}))

    def test_extract_type_raises_on_unknown_sport(self):
        command = ImportWorkoutsCommand()
        messages = {"session_mesgs": [{"sport": "swimming"}]}
        with self.assertRaises(ValueError):
            command._extract_type(messages)

    def test_extract_distance_from_session(self):
        command = ImportWorkoutsCommand()
        messages = {"session_mesgs": [{"total_distance": 10500}]}
        self.assertEqual(command._extract_distance(messages), Decimal("10.50"))

    def test_extract_distance_falls_back_to_last_record(self):
        command = ImportWorkoutsCommand()
        messages = {
            "record_mesgs": [
                {"distance": 2500},
                {"distance": 5200},
            ]
        }
        self.assertEqual(command._extract_distance(messages), Decimal("5.20"))

    def test_extract_distance_returns_none_when_missing(self):
        command = ImportWorkoutsCommand()
        self.assertIsNone(command._extract_distance({}))

    def test_extract_moving_time_from_session(self):
        command = ImportWorkoutsCommand()
        messages = {"session_mesgs": [{"total_timer_time": 2700}]}
        self.assertEqual(
            command._extract_moving_time(messages),
            timedelta(minutes=45),
        )

    def test_extract_moving_time_returns_none_when_missing(self):
        command = ImportWorkoutsCommand()
        self.assertIsNone(command._extract_moving_time({}))

    def test_extract_pace_from_session_speed(self):
        command = ImportWorkoutsCommand()
        messages = {"session_mesgs": [{"avg_speed": 3.0}]}
        # 1000 m / 3 m/s = 333.33 s per km
        self.assertEqual(
            command._extract_pace(messages),
            timedelta(seconds=333),
        )

    def test_extract_pace_from_distance_and_time(self):
        command = ImportWorkoutsCommand()
        messages = {
            "session_mesgs": [{"total_distance": 10000, "total_timer_time": 3600}]
        }
        # 10 km in 3600 s -> 360 s per km
        self.assertEqual(
            command._extract_pace(messages),
            timedelta(seconds=360),
        )

    def test_extract_pace_returns_none_when_missing(self):
        command = ImportWorkoutsCommand()
        self.assertIsNone(command._extract_pace({}))


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


class LabelModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.label = Label.objects.create(
            title="Build phase",
            colour=Label.Colour.SUCCESS,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            created_by=self.user,
        )

    def test_stores_fields(self):
        self.label.refresh_from_db()
        self.assertEqual(self.label.title, "Build phase")
        self.assertEqual(self.label.colour, "success")
        self.assertEqual(self.label.start_date, date(2026, 9, 1))
        self.assertEqual(self.label.end_date, date(2026, 9, 30))
        self.assertEqual(self.label.created_by, self.user)
        self.assertIsNotNone(self.label.created_at)
        self.assertIsNotNone(self.label.updated_at)

    def test_colour_choices_are_bootstrap_badge_colours(self):
        self.assertEqual(
            {choice[0] for choice in Label.Colour.choices},
            {
                "primary",
                "secondary",
                "success",
                "danger",
                "warning",
                "light",
                "dark",
            },
        )

    def test_colour_defaults_to_primary(self):
        label = Label.objects.create(
            title="No colour",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        self.assertEqual(label.colour, Label.Colour.PRIMARY)


class LabelViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.label = Label.objects.create(
            title="Build phase",
            colour=Label.Colour.SUCCESS,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            created_by=self.user,
        )

    def label_data(self, **overrides):
        data = {
            "title": "Recovery",
            "colour": Label.Colour.SUCCESS,
            "start_date": "2026-10-01",
            "end_date": "2026-10-14",
        }
        data.update(overrides)
        return data

    def test_list_shows_labels(self):
        response = self.client.get(reverse("alors:label_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build phase")
        self.assertContains(response, reverse("alors:label_add"))

    def test_add_sets_created_by_and_redirects(self):
        response = self.client.post(
            reverse("alors:label_add"),
            self.label_data(),
        )
        self.assertRedirects(response, reverse("alors:label_list"))
        label = Label.objects.get(title="Recovery")
        self.assertEqual(label.created_by, self.user)

    def test_add_rejects_end_before_start(self):
        response = self.client.post(
            reverse("alors:label_add"),
            self.label_data(
                start_date="2026-10-20",
                end_date="2026-10-01",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Label.objects.filter(title="Recovery").exists())

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:label_edit", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build phase")

    def test_edit_page_offers_delete(self):
        url = reverse("alors:label_delete", args=[self.label.pk])
        response = self.client.get(reverse("alors:label_edit", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, url)
        self.assertContains(response, "Delete label")

    def test_delete_removes_label(self):
        response = self.client.post(reverse("alors:label_delete", args=[self.label.pk]))
        self.assertRedirects(response, reverse("alors:label_list"))
        self.assertFalse(Label.objects.filter(pk=self.label.pk).exists())

    def test_edit_updates_label(self):
        response = self.client.post(
            reverse("alors:label_edit", args=[self.label.pk]),
            self.label_data(title="Base phase", colour=Label.Colour.WARNING),
        )
        self.assertRedirects(response, reverse("alors:label_list"))
        self.label.refresh_from_db()
        self.assertEqual(self.label.title, "Base phase")
        self.assertEqual(self.label.colour, "warning")


class CommentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="commenter", password="secret123")
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
            created_by=self.user,
        )
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
        )

    def comment(self, **overrides):
        values = {"text": "Nice session.", "created_by": self.user}
        values.update(overrides)
        return Comment.objects.create(**values)

    def test_comment_can_attach_to_planned_workout(self):
        comment = self.comment(planned_workout=self.planned)
        self.assertEqual(self.planned.comments.count(), 1)
        self.assertEqual(self.planned.comments.first(), comment)

    def test_comment_can_attach_to_workout(self):
        comment = self.comment(workout=self.workout)
        self.assertEqual(self.workout.comments.count(), 1)
        self.assertEqual(self.workout.comments.first(), comment)

    def test_multiple_comments_allowed(self):
        self.comment(planned_workout=self.planned, text="First.")
        self.comment(planned_workout=self.planned, text="Second.")
        self.assertEqual(self.planned.comments.count(), 2)

    def test_timestamps_are_set(self):
        comment = self.comment(workout=self.workout)
        comment.refresh_from_db()
        self.assertIsNotNone(comment.created_at)
        self.assertIsNotNone(comment.updated_at)

    def test_created_by_links_back_to_user(self):
        self.comment(planned_workout=self.planned)
        self.assertEqual(self.user.comments.count(), 1)

    def test_deleting_parent_deletes_comments(self):
        comment = self.comment(planned_workout=self.planned)
        self.planned.delete()
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_comment_count_starts_at_zero(self):
        self.assertEqual(self.planned.comment_count, 0)
        self.assertEqual(self.workout.comment_count, 0)

    def test_comment_count_increments_when_comment_added(self):
        self.comment(planned_workout=self.planned)
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 1)

        self.comment(workout=self.workout)
        self.comment(workout=self.workout)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.comment_count, 2)

    def test_comment_count_decrements_when_comment_removed(self):
        comment = self.comment(planned_workout=self.planned)
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 1)
        comment.delete()
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 0)


class CommentViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="commenter", password="secret123")
        self.client.force_login(self.user)
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
        )
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
        )

    def test_add_comment_to_planned_workout(self):
        response = self.client.post(
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
            {"text": "Looking **good**!"},
        )
        self.assertRedirects(
            response, reverse("alors:planned_detail", args=[self.planned.pk])
        )
        comment = Comment.objects.get(planned_workout=self.planned)
        self.assertEqual(comment.text, "Looking **good**!")
        self.assertEqual(comment.created_by, self.user)

    def test_add_comment_to_workout(self):
        response = self.client.post(
            reverse("alors:add_workout_comment", args=[self.workout.pk]),
            {"text": "Felt great!"},
        )
        self.assertRedirects(
            response, reverse("alors:workout_detail", args=[self.workout.pk])
        )
        comment = Comment.objects.get(workout=self.workout)
        self.assertEqual(comment.text, "Felt great!")
        self.assertEqual(comment.created_by, self.user)

    def test_blank_comment_is_rejected(self):
        response = self.client.post(
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
            {"text": ""},
        )
        self.assertRedirects(
            response, reverse("alors:planned_detail", args=[self.planned.pk])
        )
        self.assertFalse(Comment.objects.filter(planned_workout=self.planned).exists())

    def test_planned_detail_page_shows_comments_and_form(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="**great** run",
            created_by=self.user,
        )
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.planned.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<strong>great</strong>")
        self.assertContains(response, "Add a comment")
        self.assertContains(
            response,
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
        )

    def test_workout_detail_page_shows_comments_and_form(self):
        Comment.objects.create(
            workout=self.workout, text="Nice session", created_by=self.user
        )
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nice session")
        self.assertContains(response, "Add a comment")
        self.assertContains(
            response,
            reverse("alors:add_workout_comment", args=[self.workout.pk]),
        )


class NotificationTests(TestCase):
    def setUp(self):
        self.athlete = User.objects.create_user(username="runner", password="secret123")
        self.coach = User.objects.create_user(username="coach", password="secret123")

    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date(2026, 9, 5),
            "total_distance": Decimal("10.00"),
            "title": "Long run",
            "created_by": self.athlete,
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 4, 8, 30),
            "total_time": timedelta(minutes=50),
            "workout_type": WorkoutType.RUN,
            "created_by": self.athlete,
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def notifications_for(self, user):
        return Notification.objects.filter(recipient=user).order_by("pk")

    def latest_for(self, user):
        return self.notifications_for(user).latest("pk")

    def test_adding_planned_workout_notifies_everyone_except_actor(self):
        planned = self.create_planned()
        self.assertEqual(self.notifications_for(self.coach).count(), 1)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, planned)
        self.assertEqual(notification.actor, self.athlete)

    def test_editing_planned_workout_notifies_others(self):
        planned = self.create_planned()
        planned.title = "Long run v2"
        planned.save()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, planned)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)

    def test_adding_workout_notifies_others(self):
        workout = self.create_workout()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, workout)
        self.assertEqual(notification.actor, self.athlete)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)

    def test_editing_workout_notifies_others(self):
        workout = self.create_workout()
        workout.notes = "Tough one."
        workout.save()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, workout)

    def test_actor_is_excluded_and_recorded(self):
        planned = self.create_planned()
        # The coach edits; the coach is excluded and the athlete is notified.
        planned._notification_actor = self.coach
        planned.title = "Edited by coach"
        planned.save()
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.actor, self.coach)
        # The coach's own earlier notification (from the athlete's create) stays.
        self.assertEqual(self.notifications_for(self.coach).count(), 1)

    def test_adding_comment_notifies_others(self):
        planned = self.create_planned()
        comment = Comment.objects.create(
            planned_workout=planned,
            text="Nice session.",
            created_by=self.coach,
        )
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, comment)
        self.assertEqual(notification.actor, self.coach)
        # The coach is not notified about their own comment; their only
        # notification is still the one from the athlete's plan creation.
        self.assertEqual(self.notifications_for(self.coach).count(), 1)

    def test_editing_comment_notifies_others(self):
        planned = self.create_planned()
        comment = Comment.objects.create(
            planned_workout=planned,
            text="Nice session.",
            created_by=self.coach,
        )
        comment.text = "Updated comment."
        comment.save()
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, comment)
        self.assertEqual(notification.actor, self.coach)

    def test_notification_has_read_status_and_timestamps(self):
        self.create_planned()
        notification = self.latest_for(self.coach)
        notification.refresh_from_db()
        self.assertFalse(notification.read)
        self.assertIsNotNone(notification.created_at)
        self.assertIsNotNone(notification.updated_at)

    def test_deleting_linked_object_removes_its_notifications(self):
        planned = self.create_planned()
        content_type = ContentType.objects.get_for_model(planned)
        notifications = Notification.objects.filter(
            content_type=content_type, object_id=planned.pk
        )
        self.assertEqual(notifications.count(), 1)
        planned.delete()
        self.assertFalse(notifications.exists())

    def test_workout_edit_view_claims_owner_and_notifies_others(self):
        self.client.force_login(self.athlete)
        workout = self.create_workout(created_by=None)
        response = self.client.post(
            reverse("alors:workout_edit", args=[workout.pk]),
            {"notes": "Updated via the form."},
        )
        self.assertRedirects(
            response, reverse("alors:workout_detail", args=[workout.pk])
        )
        workout.refresh_from_db()
        self.assertEqual(workout.created_by, self.athlete)
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, workout)
        self.assertEqual(notification.actor, self.athlete)


class NotificationPageTests(TestCase):
    def setUp(self):
        self.athlete = User.objects.create_user(username="runner", password="secret123")
        self.coach = User.objects.create_user(username="coach", password="secret123")
        self.client.force_login(self.athlete)
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
            created_by=self.athlete,
        )

    def test_empty_page_shows_no_notifications_message(self):
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No notifications yet")

    def test_lists_only_the_logged_in_users_notifications(self):
        # The coach comments on the athlete's plan: the athlete is notified.
        Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "coach added a comment")
        self.assertContains(
            response,
            reverse("alors:planned_detail", args=[self.planned.pk]),
        )
        # The plan's creation only notified the coach, so it is not shown.
        self.assertNotContains(response, "planned run")

    def test_summary_mentions_workout_type_and_links_to_workout(self):
        workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
            created_by=self.athlete,
        )
        # The coach edits the athlete's workout and the athlete is notified.
        workout._notification_actor = self.coach
        workout.notes = "Updated."
        workout.save()
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "coach edited the Run workout")
        self.assertContains(
            response, reverse("alors:workout_detail", args=[workout.pk])
        )

    def test_viewing_planned_workout_marks_comment_notifications_read(self):
        comment = Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        notification = Notification.objects.get(
            recipient=self.athlete, object_id=comment.pk
        )
        self.assertFalse(notification.read)
        self.client.get(reverse("alors:planned_detail", args=[self.planned.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.read)
        # The coach's own notification (about the plan being added) stays unread.
        coach_notification = Notification.objects.get(
            recipient=self.coach, object_id=self.planned.pk
        )
        coach_notification.refresh_from_db()
        self.assertFalse(coach_notification.read)

    def test_viewing_workout_marks_direct_notifications_read(self):
        workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
            created_by=self.athlete,
        )
        workout._notification_actor = self.coach
        workout.notes = "Updated by coach."
        workout.save()
        notification = Notification.objects.get(
            recipient=self.athlete, object_id=workout.pk
        )
        self.assertFalse(notification.read)
        self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.read)

    def test_viewing_object_removes_notification_from_unread_list(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        self.client.get(reverse("alors:planned_detail", args=[self.planned.pk]))
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "added a comment")

    def test_mark_all_as_read_clears_users_notifications(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="One",
            created_by=self.coach,
        )
        Comment.objects.create(
            planned_workout=self.planned,
            text="Two",
            created_by=self.coach,
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            2,
        )
        coach_unread = Notification.objects.filter(
            recipient=self.coach, read=False
        ).count()

        response = self.client.post(reverse("alors:mark_all_notifications_read"))
        self.assertRedirects(response, reverse("alors:notifications"))
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            0,
        )
        # Another user's notifications are not touched.
        self.assertEqual(
            Notification.objects.filter(recipient=self.coach, read=False).count(),
            coach_unread,
        )

    def test_mark_all_read_only_acts_on_post(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="One",
            created_by=self.coach,
        )
        self.client.get(reverse("alors:mark_all_notifications_read"))
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            1,
        )


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")

    def test_default_role_is_athlete(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(profile.role, UserProfile.Role.ATHLETE)
        self.assertEqual(profile.role, "athlete")

    def test_can_set_coach_role(self):
        profile = UserProfile.objects.create(
            user=self.user, role=UserProfile.Role.COACH
        )
        self.assertEqual(profile.role, "coach")
        self.assertEqual(profile.get_role_display(), "Coach")

    def test_profile_is_one_to_one_with_user(self):
        UserProfile.objects.create(user=self.user)
        with self.assertRaises(Exception):
            UserProfile.objects.create(user=self.user)

    def test_related_name_links_back_to_user(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(self.user.profile, profile)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="runner",
            password="secret123",
            email="runner@example.com",
        )
        self.client.force_login(self.user)

    def test_get_creates_profile_and_shows_email_and_role(self):
        response = self.client.get(reverse("alors:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email address")
        self.assertContains(response, "runner@example.com")
        self.assertContains(response, "Role")
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_post_updates_role_and_email(self):
        response = self.client.post(
            reverse("alors:profile"),
            {"role": "coach", "email": "coach@example.com"},
        )
        self.assertRedirects(response, reverse("alors:profile"))
        profile = self.user.profile
        self.assertEqual(profile.role, "coach")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "coach@example.com")

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            reverse("alors:profile"),
            {"role": "athlete", "email": "not-an-email"},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "runner@example.com")


class PlannedStatusUpdateTests(TestCase):
    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date(2026, 9, 5),
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 5, 8, 0),
            "total_time": timedelta(minutes=50),
            "workout_type": WorkoutType.RUN,
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def test_within_10_percent_marks_done(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("10.50"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "done")

    def test_under_10_percent_marks_under(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("8.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "under")

    def test_over_10_percent_marks_over(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("12.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "over")

    def test_sums_all_workouts_of_same_type_and_day(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("5.00"))
        self.create_workout(total_distance=Decimal("5.50"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "done")

    def test_different_type_is_not_matched(self):
        planned = self.create_planned()
        self.create_workout(
            workout_type=WorkoutType.WALK,
            total_distance=Decimal("2.00"),
        )
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_different_day_is_not_matched(self):
        planned = self.create_planned()
        self.create_workout(workout_date=datetime(2026, 9, 6, 8, 0))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_planned_without_distance_is_untouched(self):
        planned = self.create_planned(total_distance=None)
        self.create_workout(total_distance=Decimal("10.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_multiple_plans_for_type_and_day_are_not_matched(self):
        first = self.create_planned()
        second = self.create_planned(title="Second run")
        self.create_workout(total_distance=Decimal("10.00"))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "")
        self.assertEqual(second.status, "")


class CleanNotificationsCommandTests(TestCase):
    def setUp(self):
        from django.utils import timezone as django_timezone

        self.now = django_timezone.now()
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            created_by=self.user,
        )

    def notification(self):
        return Notification.objects.create(
            recipient=self.user,
            actor=self.user,
            content_object=self.planned,
        )

    def age(self, notification, days):
        from django.utils import timezone as django_timezone

        Notification.objects.filter(pk=notification.pk).update(
            created_at=django_timezone.now() - timedelta(days=days)
        )

    def test_deletes_notifications_older_than_30_days(self):
        old = self.notification()
        self.age(old, 40)
        recent = self.notification()

        call_command("clean_notifications")

        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recent.pk).exists())

    def test_notifications_just_under_30_days_old_are_kept(self):
        edge = self.notification()
        self.age(edge, 29)

        call_command("clean_notifications")

        self.assertTrue(Notification.objects.filter(pk=edge.pk).exists())

    def test_days_option_changes_the_cutoff(self):
        kept = self.notification()
        self.age(kept, 20)
        removed = self.notification()
        self.age(removed, 40)

        call_command("clean_notifications", "--days", 30)

        self.assertFalse(Notification.objects.filter(pk=removed.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=kept.pk).exists())


class MarkMissCommandTests(TestCase):
    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date.today(),
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def test_marks_past_workouts_without_status_as_missed(self):
        past = self.create_planned(workout_date=date.today() - timedelta(days=3))
        call_command("mark_miss")
        past.refresh_from_db()
        self.assertEqual(past.status, "missed")

    def test_does_not_change_past_workouts_with_a_status(self):
        done = self.create_planned(
            workout_date=date.today() - timedelta(days=3),
            status="done",
        )
        call_command("mark_miss")
        done.refresh_from_db()
        self.assertEqual(done.status, "done")

    def test_does_not_mark_today_or_future_workouts(self):
        today = self.create_planned(workout_date=date.today())
        future = self.create_planned(workout_date=date.today() + timedelta(days=2))
        call_command("mark_miss")
        today.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(today.status, "")
        self.assertEqual(future.status, "")
