from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from icalendar import Calendar

from .ical import render_calendar
from .models import Issue, PlannedWorkout, WarmUp, WeeklySummary, Workout
from .utils import daily, monthly, weekly
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


class DailyUtilsTests(SimpleTestCase):
    def test_mid_week_date(self):
        self.assertEqual(
            daily("2026-09-02"),
            {
                "start": datetime(2026, 9, 2),
                "end": datetime(2026, 9, 2),
                "next": "2026-09-03",
                "previous": "2026-09-01",
            },
        )

    def test_year_boundary_rolls_over(self):
        result = daily("2026-12-31")
        self.assertEqual(result["start"], datetime(2026, 12, 31))
        self.assertEqual(result["end"], datetime(2026, 12, 31))
        self.assertEqual(result["next"], "2027-01-01")
        self.assertEqual(result["previous"], "2026-12-30")

    def test_leap_day(self):
        result = daily("2028-02-29")
        self.assertEqual(result["start"], datetime(2028, 2, 29))
        self.assertEqual(result["next"], "2028-03-01")
        self.assertEqual(result["previous"], "2028-02-28")

    def test_start_and_end_are_the_same_day(self):
        for date in ["2026-09-02", "2026-12-31"]:
            with self.subTest(date=date):
                result = daily(date)
                self.assertEqual(result["start"], result["end"])


class WeeklyUtilsTests(SimpleTestCase):
    def test_mid_week_date(self):
        self.assertEqual(
            weekly("2026-09-02"),
            {
                "start": datetime(2026, 8, 31),
                "end": datetime(2026, 9, 6),
                "next": "2026-09-07",
                "previous": "2026-08-24",
            },
        )

    def test_sunday_is_last_day_of_its_week(self):
        self.assertEqual(
            weekly("2026-09-06"),
            {
                "start": datetime(2026, 8, 31),
                "end": datetime(2026, 9, 6),
                "next": "2026-09-07",
                "previous": "2026-08-24",
            },
        )

    def test_monday_starts_a_new_week(self):
        result = weekly("2026-09-07")
        self.assertEqual(result["start"], datetime(2026, 9, 7))
        self.assertEqual(result["end"], datetime(2026, 9, 13))
        self.assertEqual(result["next"], "2026-09-14")
        self.assertEqual(result["previous"], "2026-08-31")

    def test_week_spans_monday_to_sunday(self):
        for date in ["2026-09-02", "2026-12-30", "2028-02-29"]:
            with self.subTest(date=date):
                result = weekly(date)
                self.assertEqual(result["start"].weekday(), 0)  # Monday
                self.assertEqual(result["end"].weekday(), 6)  # Sunday
                self.assertEqual(result["end"] - result["start"], timedelta(days=6))
                self.assertEqual(
                    result["next"],
                    (result["start"] + timedelta(days=7)).strftime("%Y-%m-%d"),
                )
                self.assertEqual(
                    result["previous"],
                    (result["start"] - timedelta(days=7)).strftime("%Y-%m-%d"),
                )


class MonthlyUtilsTests(SimpleTestCase):
    def test_mid_month_date(self):
        self.assertEqual(
            monthly("2026-09-02"),
            {
                "start": datetime(2026, 9, 1),
                "end": datetime(2026, 9, 30),
                "next": "2026-10-01",
                "previous": "2026-08-01",
            },
        )

    def test_january_previous_month_crosses_year(self):
        result = monthly("2026-01-15")
        self.assertEqual(result["start"], datetime(2026, 1, 1))
        self.assertEqual(result["end"], datetime(2026, 1, 31))
        self.assertEqual(result["next"], "2026-02-01")
        self.assertEqual(result["previous"], "2025-12-01")

    def test_december_next_month_crosses_year(self):
        result = monthly("2026-12-15")
        self.assertEqual(result["start"], datetime(2026, 12, 1))
        self.assertEqual(result["end"], datetime(2026, 12, 31))
        self.assertEqual(result["next"], "2027-01-01")
        self.assertEqual(result["previous"], "2026-11-01")

    def test_leap_year_february(self):
        result = monthly("2028-02-29")
        self.assertEqual(result["start"], datetime(2028, 2, 1))
        self.assertEqual(result["end"], datetime(2028, 2, 29))
        self.assertEqual(result["next"], "2028-03-01")
        self.assertEqual(result["previous"], "2028-01-01")

    def test_given_date_is_inside_returned_range(self):
        for date in ["2026-09-02", "2026-12-15", "2028-02-29"]:
            with self.subTest(date=date):
                result = monthly(date)
                parsed = datetime.strptime(date, "%Y-%m-%d")
                self.assertEqual(result["start"].day, 1)  # first of the month
                self.assertLessEqual(result["start"], parsed)
                self.assertGreaterEqual(result["end"], parsed)


class LoggedOutViewTests(TestCase):
    """Workout views must not be usable by a logged-out user.

    Every @login_required view should respond with a redirect to the
    login page (carrying the requested URL as the ``next`` parameter)
    when the user is not authenticated.
    """

    def setUp(self):
        self.workout = PlannedWorkout.objects.create(
            workout_type=PlannedWorkout.WorkoutType.RUN,
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
            workout_type=PlannedWorkout.WorkoutType.RUN,
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
            workout_type=PlannedWorkout.WorkoutType.WALK,
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
                "workout_type": PlannedWorkout.WorkoutType.RUN,
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
                "workout_type": PlannedWorkout.WorkoutType.RUN,
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
            workout_type=PlannedWorkout.WorkoutType.RUN,
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
            "workout_date": date(2026, 9, 5),
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
            average_speed=None,
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
            workout_date=date(2026, 9, 5),
            total_time=timedelta(hours=1, minutes=2, seconds=3),
            workout_type="run",
            total_distance=10.5,
            moving_time=timedelta(minutes=58),
            average_speed=10.86,
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
            "Run workout",
            "Sept. 5, 2026",
            "1:02:03",
            "10.50 km",
            "0:58:00",
            "10.86 km/h",
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
            workout_date=date(2026, 9, 5),
            total_time=timedelta(hours=1),
            workout_type="run",
            total_distance=10.5,
            moving_time=timedelta(minutes=58),
            average_speed=10.86,
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
        self.assertEqual(self.workout.workout_date, date(2026, 9, 5))
        self.assertEqual(self.workout.workout_type, "run")
        self.assertEqual(self.workout.total_time, timedelta(hours=1))
        self.assertEqual(self.workout.total_distance, Decimal("10.5"))
        self.assertEqual(self.workout.moving_time, timedelta(minutes=58))
        self.assertEqual(self.workout.average_speed, Decimal("10.86"))

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
    def create_workout(self, workout_date, distance="10.00", workout_type="run"):
        return PlannedWorkout.objects.create(
            workout_type=workout_type,
            workout_date=workout_date,
            total_distance=distance,
        )

    def create_workout_record(self, workout_date, distance="10.00", workout_type="run"):
        return Workout.objects.create(
            workout_date=workout_date,
            total_time=timedelta(minutes=30),
            workout_type=workout_type,
            total_distance=distance,
        )

    def summary_for(self, sunday):
        return WeeklySummary.objects.get(date=sunday)

    def test_add_workout_creates_summary_for_sundays_week(self):
        self.create_workout(date(2026, 9, 2))  # Wednesday
        summary = self.summary_for(date(2026, 9, 6))  # that week's Sunday
        self.assertEqual(summary.summary["planned_workouts"], 1)
        self.assertEqual(summary.summary["planned_distance_km"], 10.0)
        self.assertEqual(summary.summary["types"], {"Run": 1})

    def test_multiple_workouts_same_week_update_one_summary(self):
        self.create_workout(date(2026, 9, 2), distance="10.00")  # Wed
        self.create_workout(date(2026, 9, 4), distance="3.00", workout_type="walk")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["planned_workouts"], 2)
        self.assertEqual(summary.summary["planned_distance_km"], 13.0)
        self.assertEqual(summary.summary["types"], {"Run": 1, "Walk": 1})

    def test_workout_in_other_week_creates_separate_summary(self):
        self.create_workout(date(2026, 9, 2))  # week ending 2026-09-06
        self.create_workout(date(2026, 9, 7))  # week ending 2026-09-13
        self.assertEqual(
            self.summary_for(date(2026, 9, 6)).summary["planned_workouts"], 1
        )
        self.assertEqual(
            self.summary_for(date(2026, 9, 13)).summary["planned_workouts"], 1
        )

    def test_updating_workout_refreshes_summary(self):
        workout = self.create_workout(date(2026, 9, 2), distance="10.00")
        workout.total_distance = "12.50"
        workout.save()
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["planned_distance_km"], 12.5)

    def test_moving_workout_to_another_week_updates_both_weeks(self):
        workout = self.create_workout(date(2026, 9, 2))  # week ending 09-06
        workout.workout_date = date(2026, 9, 10)  # week ending 09-13
        workout.save()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        summary = self.summary_for(date(2026, 9, 13))
        self.assertEqual(summary.summary["planned_workouts"], 1)

    def test_deleting_only_workout_removes_weekly_summary(self):
        workout = self.create_workout(date(2026, 9, 2))
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        workout.delete()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())

    def test_deleting_one_workout_updates_weekly_summary(self):
        self.create_workout(date(2026, 9, 2), distance="10.00")
        to_delete = self.create_workout(date(2026, 9, 4), distance="3.00")
        to_delete.delete()
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["planned_workouts"], 1)
        self.assertEqual(summary.summary["planned_distance_km"], 10.0)

    def test_add_workout_record_creates_summary_under_workout_keys(self):
        self.create_workout_record(date(2026, 9, 2), distance="10.00")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["workouts"], 1)
        self.assertEqual(summary.summary["workout_distance_km"], 10.0)
        self.assertEqual(summary.summary["workout_types"], {"Run": 1})
        # Planned keys stay empty for a completed-only week.
        self.assertEqual(summary.summary["planned_workouts"], 0)
        self.assertEqual(summary.summary["planned_distance_km"], 0.0)

    def test_planned_and_workout_data_kept_in_separate_keys(self):
        self.create_workout(date(2026, 9, 2), distance="10.00")  # planned run
        self.create_workout_record(
            date(2026, 9, 4), distance="5.00", workout_type="walk"
        )
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary,
            {
                "planned_workouts": 1,
                "planned_distance_km": 10.0,
                "types": {"Run": 1},
                "workouts": 1,
                "workout_distance_km": 5.0,
                "workout_total_time_seconds": 1800,  # 30 minutes
                "workout_types": {"Walk": 1},
            },
        )

    def test_workout_total_time_is_summed_across_week(self):
        self.create_workout_record(date(2026, 9, 2), workout_type="run")
        self.create_workout_record(date(2026, 9, 4), workout_type="walk")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["workouts"], 2)
        self.assertEqual(
            summary.summary["workout_total_time_seconds"],
            2 * 30 * 60,
        )

    def test_updating_workout_record_refreshes_summary(self):
        record = self.create_workout_record(date(2026, 9, 2), distance="10.00")
        record.total_distance = "15.00"
        record.save()
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["workout_distance_km"], 15.0)

    def test_moving_workout_record_to_another_week_updates_both_weeks(self):
        record = self.create_workout_record(date(2026, 9, 2))  # week ending 09-06
        record.workout_date = date(2026, 9, 10)  # week ending 09-13
        record.save()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        summary = self.summary_for(date(2026, 9, 13))
        self.assertEqual(summary.summary["workouts"], 1)

    def test_deleting_workout_record_removes_weekly_summary(self):
        record = self.create_workout_record(date(2026, 9, 2))
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        record.delete()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
