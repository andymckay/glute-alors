from datetime import date

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from icalendar import Calendar

from ..ical import render_calendar
from ..models import PlannedWorkout, WarmUp, WorkoutType


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
