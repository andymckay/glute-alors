import json
import unittest
from datetime import datetime, timedelta, timezone

from ..fit import Fit


class FitSeriesTests(unittest.TestCase):
    """Tests for the heart-rate/pace/elevation/power/distance series."""

    def make_fit(self, data):
        return Fit(json.loads(data))

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

    def test_returns_heart_rate_series(self):
        fit = self.make_fit(self.hr_data())
        series = fit.get_heart_rate_series()
        self.assertEqual(len(series), 3)
        self.assertAlmostEqual(series[0][0], 0.0)
        self.assertAlmostEqual(series[1][0], 60.0)
        self.assertEqual([hr for _, hr in series], [120, 150, 135])

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

    def test_returns_pace_series(self):
        fit = self.make_fit(self.pace_data())
        series = fit.get_pace_series()
        self.assertEqual(len(series), 3)
        # 1000 m at 4 m/s = 250 s/km, at 5 m/s = 200 s/km.
        self.assertAlmostEqual(series[0][1], 250.0)
        self.assertAlmostEqual(series[1][1], 200.0)

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

    def test_returns_elevation_series(self):
        fit = self.make_fit(self.elevation_data())
        series = fit.get_elevation_series()
        self.assertEqual([alt for _, alt in series], [100.0, 120.0, 95.0])

    def gain_loss_data(self):
        return json.dumps(
            {
                "record_mesgs": [
                    {
                        "timestamp": "2026-09-04T08:00:00+00:00",
                        "altitude": 100.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:01:00+00:00",
                        "altitude": 110.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:02:00+00:00",
                        "altitude": 105.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:03:00+00:00",
                        "altitude": 130.0,
                    },
                    {
                        "timestamp": "2026-09-04T08:04:00+00:00",
                        "altitude": 125.0,
                    },
                ]
            }
        )

    def test_returns_elevation_gain(self):
        fit = self.make_fit(self.gain_loss_data())
        self.assertAlmostEqual(fit.elevation_gain(), 35.0)

    def test_returns_elevation_loss(self):
        fit = self.make_fit(self.gain_loss_data())
        self.assertAlmostEqual(fit.elevation_loss(), 10.0)

    def test_no_altitude_means_no_gain_or_loss(self):
        fit = self.make_fit(self.hr_data())
        self.assertEqual(fit.elevation_gain(), 0.0)
        self.assertEqual(fit.elevation_loss(), 0.0)

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

    def test_returns_power_series(self):
        fit = self.make_fit(self.power_data())
        series = fit.get_power_series()
        self.assertEqual(len(series), 3)
        self.assertAlmostEqual(series[0][0], 0.0)
        self.assertAlmostEqual(series[1][0], 60.0)
        self.assertEqual([watts for _, watts in series], [180.0, 240.0, 210.0])

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

    def test_returns_distance_series(self):
        fit = self.make_fit(self.distance_data())
        series = fit.get_distance_series()
        self.assertEqual([sec for sec, _ in series], [0.0, 60.0, 120.0])
        self.assertAlmostEqual(series[0][1], 0.0)
        self.assertAlmostEqual(series[1][1], 0.25)
        self.assertAlmostEqual(series[2][1], 0.5)


class FitSplitsTests(unittest.TestCase):
    """Tests for per-kilometre split generation."""

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

    def test_returns_km_splits(self):
        fit = Fit(json.loads(self.split_data()))
        splits = fit.get_splits()
        self.assertEqual([split["distance"] for split in splits], [1.0, 2.0, 3.0])
        self.assertEqual([split["split_distance"] for split in splits], [1.0, 1.0, 1.0])
        for split in splits:
            self.assertAlmostEqual(split["time"], 300.0)
            self.assertAlmostEqual(split["avg_pace"], 300.0)
            self.assertAlmostEqual(split["max_pace"], 300.0)
        self.assertAlmostEqual(splits[0]["avg_hr"], 130.0)
        self.assertAlmostEqual(splits[1]["avg_hr"], 140.0)
        self.assertAlmostEqual(splits[2]["max_hr"], 150.0)

    def test_no_distance_records_means_no_splits(self):
        fit = Fit({})
        self.assertEqual(fit.get_splits(), [])

    def lap_data(self):
        """3 km at 5:00/km with two device laps: 2 km then 1 km."""
        records = []
        base = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
        for index in range(31):
            km = index * 0.1
            records.append(
                {
                    "timestamp": (base + timedelta(seconds=30 * index)).isoformat(),
                    "distance": km * 1000.0,
                    "heart_rate": 130,
                }
            )
        return json.dumps(
            {
                "record_mesgs": records,
                "lap_mesgs": [
                    {"total_distance": 2000.0},
                    {"total_distance": 1000.0},
                ],
            }
        )

    def test_uses_device_laps_when_present(self):
        fit = Fit(json.loads(self.lap_data()))
        splits = fit.get_splits()
        self.assertEqual([split["distance"] for split in splits], [2.0, 3.0])
        self.assertEqual([split["split_distance"] for split in splits], [2.0, 1.0])
        self.assertAlmostEqual(splits[0]["time"], 600.0)
        self.assertAlmostEqual(splits[1]["time"], 300.0)


class FitRouteTests(unittest.TestCase):
    """Tests for GPS route-point extraction."""

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

    def test_returns_route_points(self):
        fit = Fit(json.loads(self.route_data()))
        route = fit.get_route_points()
        self.assertEqual(len(route), 3)
        self.assertAlmostEqual(route[0][0], 49.2827)
        self.assertAlmostEqual(route[0][1], -123.1207)
