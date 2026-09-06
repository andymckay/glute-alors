import json
from datetime import datetime, timedelta, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import Workout, WorkoutType


class HeartRateGraphTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)

    def create_workout(self, workout_data=""):
        return Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=45),
            workout_type=WorkoutType.RUN,
            workout_data=workout_data,
        )

    def hr_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "heart_rate": 120,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "heart_rate": 150,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "heart_rate": 135,
                    },
                ]
            }
        )

    def test_detail_page_renders_heart_rate_graph(self):
        workout = self.create_workout(self.hr_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg")
        self.assertContains(response, "<polyline")
        self.assertContains(response, "hr-chart")
        self.assertContains(response, "data-series=")
        self.assertContains(response, 'data-metric="hr"')
        self.assertContains(response, "Heart")

    def test_no_heart_rate_data_means_no_graph(self):
        workout = self.create_workout()
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-metric="hr"')

    def pace_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "speed": 4.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "speed": 5.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "speed": 3.333,
                    },
                ]
            }
        )

    def test_detail_page_renders_pace_graph(self):
        workout = self.create_workout(self.pace_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<polyline")
        self.assertContains(response, 'data-metric="pace"')

    def test_no_pace_data_means_no_pace_graph(self):
        workout = self.create_workout(self.hr_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-metric="pace"')

    def elevation_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "altitude": 100.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "altitude": 120.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "altitude": 95.0,
                    },
                ]
            }
        )

    def test_detail_page_renders_elevation_graph(self):
        workout = self.create_workout(self.elevation_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<polyline")
        self.assertContains(response, 'data-metric="elevation"')

    def test_no_elevation_data_means_no_elevation_graph(self):
        workout = self.create_workout(self.hr_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-metric="elevation"')

    def power_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "power": 180,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "power": 240,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "power": 210,
                    },
                ]
            }
        )

    def test_detail_page_renders_power_graph(self):
        workout = self.create_workout(self.power_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<polyline")
        self.assertContains(response, 'data-metric="power"')
        self.assertContains(response, "Power")

    def test_no_power_data_means_no_power_graph(self):
        workout = self.create_workout(self.hr_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-metric="power"')

    def distance_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "heart_rate": 120,
                        "distance": 0.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "heart_rate": 150,
                        "distance": 250.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "heart_rate": 135,
                        "distance": 500.0,
                    },
                ]
            }
        )

    def test_detail_page_embeds_distance_data_for_tooltips(self):
        workout = self.create_workout(self.distance_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-metric="hr"')
        self.assertContains(response, "data-distance=")


class WorkoutSplitsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)

    def split_data(self):
        """3 km at a constant 5:00/km, HR ~130/140/150 per km."""
        records = []
        base = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
        for index in range(31):
            km = index * 0.1
            hr = 130 if km <= 1.0 else (140 if km <= 2.0 else 150)
            records.append(
                {
                    "timestamp": (base + timedelta(seconds=30 * index)).isoformat(),
                    "distance": km * 1000.0,
                    "heart_rate": hr,
                }
            )
        return json.dumps({"record_mesgs": records})

    def create_workout(self, data=""):
        return Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=15),
            workout_type=WorkoutType.RUN,
            workout_data=data,
        )

    def test_detail_page_renders_splits_table(self):
        workout = self.create_workout(self.split_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<table")
        self.assertContains(response, '<th scope="col">Split</th>')
        self.assertContains(response, '<th scope="col">Total</th>')
        self.assertContains(response, "Avg pace")
        self.assertContains(response, "Max HR")

    def test_detail_page_hides_splits_without_data(self):
        workout = self.create_workout()
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<table")


class RouteMapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)

    def create_workout(self, data=""):
        return Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=45),
            workout_type=WorkoutType.RUN,
            workout_data=data,
        )

    def route_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "position_lat": 49.2827,
                        "position_long": -123.1207,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "position_lat": 49.2837,
                        "position_long": -123.1187,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "position_lat": 49.2847,
                        "position_long": -123.1167,
                    },
                ]
            }
        )

    def test_detail_page_renders_map_with_route(self):
        workout = self.create_workout(self.route_data())
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="workout-map"')
        self.assertContains(response, "tile.openstreetmap.org")

    def test_no_gps_data_means_no_map(self):
        workout = self.create_workout()
        response = self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="workout-map"')
