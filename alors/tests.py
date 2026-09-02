from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import PlannedWorkout
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
