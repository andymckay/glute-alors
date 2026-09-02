from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from icalendar import Calendar

from .ical import render_calendar
from .models import PlannedWorkout, WarmUp
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
                self.assertEqual(
                    result["end"] - result["start"], timedelta(days=6)
                )
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
        url = reverse("alors:add_planned_workout")
        self.assert_login_required("get", url)

    def test_planned_workout_detail_requires_login(self):
        url = reverse("alors:planned_workout_detail", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_edit_planned_workout_requires_login(self):
        url = reverse("alors:edit_planned_workout", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_delete_planned_workout_requires_login(self):
        url = reverse("alors:delete_planned_workout", args=[self.workout.pk])
        self.assert_login_required("post", url)

    def test_workout_is_not_deleted_by_anonymous_delete(self):
        """An anonymous POST to delete must not delete the workout."""
        url = reverse("alors:delete_planned_workout", args=[self.workout.pk])
        self.assert_login_required("post", url)
        self.assertTrue(PlannedWorkout.objects.filter(pk=self.workout.pk).exists())

    def test_planned_workout_webcal_requires_login(self):
        url = reverse("alors:planned_workout_webcal")
        self.assert_login_required("get", url)

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
        response = self.client.get(reverse("alors:planned_workout_webcal"))
        self.assertEqual(response.status_code, 200)
        return Calendar.from_ical(response.content)

    def test_feed_returns_icalendar_content_type(self):
        response = self.client.get(reverse("alors:planned_workout_webcal"))
        self.assertTrue(response["Content-Type"].startswith("text/calendar"))

    def test_feed_sets_download_filename(self):
        response = self.client.get(reverse("alors:planned_workout_webcal"))
        self.assertIn("planned-workouts.ics", response["Content-Disposition"])

    def test_feed_contains_a_vevent_for_each_workout(self):
        calendar = self.feed_calendar()
        events = list(calendar.walk("VEVENT"))
        self.assertEqual(len(events), 1)

    def test_vevent_has_expected_details(self):
        calendar = self.feed_calendar()
        (event,) = calendar.walk("VEVENT")
        self.assertEqual(event.get("uid"), f"planned-workout-{self.workout.pk}@glute-alors")
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
            reverse("alors:add_planned_workout"),
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
            reverse("alors:add_planned_workout"),
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
        response = self.client.get(
            reverse("alors:warmup_edit", args=[self.warmup.pk])
        )
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
        template = Template(
            "{% load markdown_extras %}{{ value|markdown }}"
        )
        return template.render(Context({"value": value}))

    def test_renders_headings(self):
        self.assertIn("<h1>Heading</h1>", self.render("# Heading"))

    def test_renders_emphasis(self):
        self.assertIn("<strong>bold</strong>", self.render("**bold**"))

    def test_empty_value_renders_nothing(self):
        self.assertEqual(self.render(""), "")

    def test_output_is_marked_safe(self):
        template = Template(
            "{% load markdown_extras %}{{ value|markdown }}"
        )
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
            reverse("alors:planned_workout_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Warm up heading</h1>")
        self.assertContains(response, "<strong>instructions</strong>")

    def test_detail_renders_notes_as_markdown(self):
        response = self.client.get(
            reverse("alors:planned_workout_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Notes</h1>")
        self.assertContains(response, "<strong>pace</strong>")
