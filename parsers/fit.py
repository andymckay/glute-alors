from dateutil.parser import isoparse
import json
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Distances are converted from metres to kilometres with two decimals.
KM_DECIMAL_PLACES = Decimal("0.01")

# Garmin FIT sport -> workout type values, matching WorkoutType choices.
# They are plain strings so this package stays free of Django imports
# (alors.models imports this module).
SPORT_MAP = {
    "running": "run",
    "walking": "walk",
    "hiking": "hike",
    "cycling": "run",
    "racing": "run",
    "training": "strength",
}


def _to_datetime(value):
    """Coerce an epoch timestamp (seconds) or a datetime to a naive datetime.

    FIT timestamps are UTC and the project runs with ``USE_TZ = False``, so the
    timezone is dropped while keeping the UTC wall clock.  That is also what the
    rows imported before the switch hold, so old and new workouts line up.
    """
    if isinstance(value, datetime):
        converted = value
    elif isinstance(value, (int, float)):
        converted = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        return None

    if converted.tzinfo is not None:
        converted = converted.astimezone(timezone.utc).replace(tzinfo=None)
    return converted


def _messages_for(messages, *keys):
    """Return the first message found under any of ``keys``."""
    for key in keys:
        value = messages.get(key)
        if isinstance(value, list) and value:
            return value[0]
        if isinstance(value, dict):
            return value
    return None


def _seconds_at_distance(samples, distance):
    """Return the elapsed seconds at ``distance`` (km) from ``(seconds, km)`` samples.

    The value between two samples is interpolated, so the halfway point of a
    workout does not have to line up with a recorded point.
    """
    if distance <= samples[0][1]:
        return samples[0][0]

    previous_seconds, previous_distance = samples[0]
    for seconds, km in samples[1:]:
        if km >= distance:
            span = km - previous_distance
            if span <= 0:
                return seconds
            ratio = (distance - previous_distance) / span
            return previous_seconds + ratio * (seconds - previous_seconds)
        previous_seconds, previous_distance = seconds, km
    return samples[-1][0]


class Parser:
    def get_datetime(self):
        raise NotImplementedError

    def get_total_time(self):
        raise NotImplementedError

    def get_workout_type(self):
        raise NotImplementedError

    def get_distance(self):
        raise NotImplementedError

    def get_moving_time(self):
        raise NotImplementedError

    def get_pace(self):
        raise NotImplementedError

    def get_heart_rate_series(self, max_points=300):
        raise NotImplementedError

    def get_pace_series(self, max_points=300):
        raise NotImplementedError

    def get_elevation_series(self, max_points=300):
        raise NotImplementedError

    def elevation_gain(self):
        raise NotImplementedError

    def elevation_loss(self):
        raise NotImplementedError

    def negative_split(self):
        raise NotImplementedError

    def get_power_series(self, max_points=300):
        raise NotImplementedError

    def get_distance_series(self, max_points=300):
        raise NotImplementedError

    def get_route_points(self, max_points=500):
        raise NotImplementedError

    def get_splits(self):
        raise NotImplementedError

    def get_recorded_on(self):
        raise NotImplementedError


class NullParser(Parser):
    """
    For when there's no data, just returns empty results
    """

    def get_datetime(self):
        return None

    def get_total_time(self):
        return None

    def get_workout_type(self):
        return None

    def get_distance(self):
        return None

    def get_moving_time(self):
        return None

    def get_pace(self):
        return None

    def get_heart_rate_series(self, max_points=300):
        return []

    def get_pace_series(self, max_points=300):
        return []

    def get_elevation_series(self, max_points=300):
        return []

    def elevation_gain(self):
        return 0.0

    def elevation_loss(self):
        return 0.0

    def negative_split(self):
        return False

    def get_power_series(self, max_points=300):
        return []

    def get_distance_series(self, max_points=300):
        return []

    def get_route_points(self, max_points=500):
        return []

    def get_splits(self):
        return []

    def get_recorded_on(self):
        return ""


class Fit(Parser):
    """
    Various functions to get useful information out of FIT data.
    """

    def __init__(self, workout_data):
        """Keep the decoded FIT messages and the parts used most often."""
        data = workout_data

        self.data = data
        self.records = data.get("record_mesgs") or []
        self.laps = data.get("lap_mesgs") or []
        self.device = data.get("device_info_mesgs") or []

    def get_datetime(self):
        """Workout datetime from the first activity/record timestamp, else now."""
        activities = self.data.get("activity_mesgs") or []
        if isinstance(activities, dict):
            activities = [activities]
        for activity in activities:
            timestamp = _to_datetime(activity.get("timestamp"))
            if timestamp is not None:
                return timestamp

        for record in self.records:
            timestamp = _to_datetime(record.get("timestamp"))
            if timestamp is not None:
                return timestamp

        return datetime.now(timezone.utc).replace(tzinfo=None)

    def get_total_time(self):
        """Total time from the first and last record timestamps."""
        timestamps = []
        for record in self.records:
            timestamp = _to_datetime(record.get("timestamp"))
            if timestamp is not None:
                timestamps.append(timestamp)

        if len(timestamps) >= 2:
            seconds = (max(timestamps) - min(timestamps)).total_seconds()
            return timedelta(seconds=max(0, int(seconds)))
        return timedelta(0)

    def get_workout_type(self):
        """Best-effort workout type from the session sport field."""
        session = _messages_for(self.data, "session_mesgs")
        if session is not None:
            sport = session.get("sport")
            if isinstance(sport, str):
                if sport.lower() not in SPORT_MAP:
                    raise ValueError("Unknown sport:", sport.lower())
                return SPORT_MAP[sport.lower()]
        return None

    def get_distance(self):
        """Total distance in km, from the session or the last record message.

        FIT distances are expressed in meters.
        """
        session = _messages_for(self.data, "session_mesgs")
        if session is not None:
            meters = session.get("total_distance")
            if meters:
                return (Decimal(str(meters)) / Decimal(1000)).quantize(
                    KM_DECIMAL_PLACES
                )

        cumulative = None
        for record in self.records:
            distance = record.get("distance")
            if distance is not None:
                cumulative = distance
        if cumulative:
            return (Decimal(str(cumulative)) / Decimal(1000)).quantize(
                KM_DECIMAL_PLACES
            )
        return None

    def get_moving_time(self):
        """Moving time from the session's active timer (in seconds)."""
        session = _messages_for(self.data, "session_mesgs")
        if session is not None:
            seconds = session.get("total_timer_time")
            if seconds:
                return timedelta(seconds=int(seconds))
        return None

    def get_pace(self):
        """Average pace (time per km), from session speed or distance/time.

        FIT speed is expressed in meters per second, so pace in seconds per
        kilometer is 1000 / speed.
        """
        session = _messages_for(self.data, "session_mesgs")
        if session is not None:
            meters_per_second = session.get("avg_speed")
            if meters_per_second:
                seconds_per_km = Decimal(1000) / Decimal(str(meters_per_second))
                return timedelta(seconds=int(seconds_per_km))

        moving_time = self.get_moving_time()
        distance_km = self.get_distance()
        seconds = moving_time.total_seconds() if moving_time else 0
        if distance_km and seconds > 0:
            seconds_per_km = Decimal(seconds) / Decimal(str(distance_km))
            return timedelta(seconds=int(seconds_per_km))
        return None

    def _record_series(self, extract, max_points=300):
        """Build ``(seconds, value)`` samples from the FIT records.

        ``extract`` maps a record to a numeric value (or ``None`` to skip it).
        Times are seconds from the first record; if timestamps are unusable the
        value is plotted against the record index instead.
        """
        if not self.records:
            return []

        samples = []
        start = None
        usable = True
        for record in self.records:
            value = extract(record)
            if value is None:
                continue
            timestamp = record.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = isoparse(timestamp)
                except (ValueError, TypeError, OverflowError):
                    usable = False
                    break
            if start is None:
                start = timestamp
                seconds = 0.0
            else:
                try:
                    if isinstance(timestamp, (int, float)):
                        seconds = float(timestamp) - float(start)
                    else:
                        seconds = (timestamp - start).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    usable = False
                    break
            if seconds < 0:
                usable = False
                break
            samples.append((seconds, value))

        if not usable:
            values = [
                extracted
                for record in records
                if (extracted := extract(record)) is not None
            ]
            samples = [(float(i), value) for i, value in enumerate(values)]

        if len(samples) < 2:
            return []
        if len(samples) > max_points:
            step = len(samples) / float(max_points)
            samples = [samples[int(i * step)] for i in range(max_points)]
        return samples

    def get_heart_rate_series(self, max_points=300):
        """Return ``(seconds, bpm)`` samples from the decoded FIT records."""
        return self._record_series(
            lambda record: (
                None if record.get("heart_rate") is None else int(record["heart_rate"])
            ),
            max_points,
        )

    def get_pace_series(self, max_points=300):
        """Return ``(seconds, seconds_per_km)`` samples from the FIT records."""

        def seconds_per_km(record):
            speed = record.get("speed")
            if speed is None:
                return None
            speed = float(speed)
            if speed <= 0:
                return None
            return 1000.0 / speed

        return self._record_series(seconds_per_km, max_points)

    def get_elevation_series(self, max_points=300):
        """Return ``(seconds, altitude_m)`` samples from the FIT records."""

        def altitude(record):
            value = record.get("altitude")
            if value is None:
                return None
            return float(value)

        return self._record_series(altitude, max_points)

    def _elevation_totals(self):
        """Return ``(gain, loss)`` in metres between consecutive records.

        Records without an ``altitude`` are skipped; ``loss`` is returned as a
        positive number.
        """
        gain = 0.0
        loss = 0.0
        previous = None
        for record in self.records:
            altitude = record.get("altitude")
            if altitude is None:
                continue
            try:
                altitude = float(altitude)
            except (TypeError, ValueError):
                continue
            if previous is not None:
                delta = altitude - previous
                if delta > 0:
                    gain += delta
                else:
                    loss -= delta
            previous = altitude
        return gain, loss

    def elevation_gain(self):
        """Return the total elevation gained in metres."""
        return self._elevation_totals()[0]

    def elevation_loss(self):
        """Return the total elevation lost in metres."""
        return self._elevation_totals()[1]

    def negative_split(self):
        """Return True when the second half of the activity was faster.

        The time taken to cover the first and the second half of the recorded
        distance is compared, interpolating the time at the halfway point. A
        workout without usable distances or timestamps returns False, as does
        an even split.
        """
        # Ask for every sample: get_distance_series decimates long series.
        samples = self.get_distance_series(max_points=len(self.records))
        if len(samples) < 2:
            return False

        total_distance = samples[-1][1]
        if total_distance <= 0:
            return False

        first_half = _seconds_at_distance(samples, total_distance / 2.0)
        second_half = samples[-1][0] - first_half
        return second_half < first_half

    def get_power_series(self, max_points=300):
        """Return ``(seconds, watts)`` samples from the decoded FIT records."""

        def watts(record):
            value = record.get("power")
            if value is None:
                return None
            return float(value)

        return self._record_series(watts, max_points)

    def get_distance_series(self, max_points=300):
        """Return ``(seconds, km)`` cumulative distance samples."""

        def km(record):
            distance = record.get("distance")
            if distance is None:
                return None
            return float(distance) / 1000.0

        return self._record_series(km, max_points)

    def get_route_points(self, max_points=500):
        """Return the workout's GPS track as ``[lat, lon]`` pairs (degrees)."""
        points = []
        for record in self.records:
            lat = record.get("position_lat")
            lon = record.get("position_long")
            if lat is None or lon is None:
                continue
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                continue
            # FIT positions can be stored as semicircles; convert to degrees.
            if abs(lat) > 90 or abs(lon) > 180:
                lat = lat * (180.0 / 2**31)
                lon = lon * (180.0 / 2**31)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            points.append([round(lat, 6), round(lon, 6)])

        if len(points) > max_points:
            step = len(points) / float(max_points)
            points = [points[int(i * step)] for i in range(max_points)]
        return points

    def get_recorded_on(self):
        try:
            return self.device[0].get("product_name")
        except (ValueError, IndexError):
            return "Unknown"

    def get_splits(self):
        """Return per-kilometre (and lap) splits from the FIT records.

        Each split is a dict with the split's end distance in km, duration in
        seconds, average/max pace (seconds per km) and average/max heart rate.
        Rows are added at every whole kilometre and wherever a recorded lap
        ends, plus a final partial segment up to the total distance.
        """
        if not self.records:
            return []

        times = []
        kms = []
        heart_rates = []
        record_paces = []
        start = None
        usable = True
        for record in self.records:
            distance = record.get("distance")
            if distance is None:
                continue
            try:
                distance = float(distance)
            except (TypeError, ValueError):
                continue

            hr = record.get("heart_rate")
            speed = record.get("speed")
            if speed is not None:
                try:
                    speed = float(speed)
                except (TypeError, ValueError):
                    speed = None
            timestamp = record.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = isoparse(timestamp)
                except (ValueError, TypeError, OverflowError):
                    usable = False
                    break
            if start is None:
                start = timestamp
                seconds = 0.0
            else:
                try:
                    if isinstance(timestamp, (int, float)):
                        seconds = float(timestamp) - float(start)
                    else:
                        seconds = (timestamp - start).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    usable = False
                    break
            if seconds < 0:
                usable = False
                break
            times.append(seconds)
            kms.append(distance / 1000.0)
            heart_rates.append(None if hr is None else float(hr))
            record_paces.append(1000.0 / speed if speed and speed > 0 else None)

        if not usable or len(times) < 2:
            return []

        total_km = kms[-1]
        if total_km <= 0:
            return []

        lap_ends = []
        lap_total = 0.0
        for lap in self.laps or []:
            length = lap.get("total_distance")
            if not length:
                continue
            lap_total += float(length) / 1000.0
            lap_ends.append(lap_total)

        if lap_ends:
            merged = sorted(
                {round(end, 4) for end in lap_ends if end <= total_km + 0.01}
            )
            if not merged or merged[-1] < total_km - 0.01:
                merged.append(total_km)
        else:
            merged = [float(km) for km in range(1, int(total_km) + 1)]
            if total_km - int(total_km) > 0.0005:
                merged.append(total_km)

        def time_at(target_km):
            index = bisect_left(kms, target_km)
            if index <= 0:
                return times[0]
            if index >= len(kms):
                return times[-1]
            km_before, km_after = kms[index - 1], kms[index]
            if km_after <= km_before:
                return times[index]
            fraction = (target_km - km_before) / (km_after - km_before)
            return times[index - 1] + fraction * (times[index] - times[index - 1])

        splits = []
        previous = 0.0
        for boundary in merged:
            segment_km = boundary - previous
            if segment_km <= 0.0005:
                previous = boundary
                continue

            lo = bisect_right(kms, previous + 1e-9)
            hi = bisect_right(kms, boundary + 1e-9)
            segment_hr = [hr for hr in heart_rates[lo:hi] if hr is not None]

            duration = max(0.0, time_at(boundary) - time_at(previous))

            fastest = None
            speed_paces = [pace for pace in record_paces[lo:hi] if pace is not None]
            if speed_paces:
                fastest = min(speed_paces)
            else:
                for index in range(lo, hi - 1):
                    delta_km = kms[index + 1] - kms[index]
                    delta_time = times[index + 1] - times[index]
                    if delta_km > 0 and delta_time >= 0:
                        pace = delta_time / delta_km
                        if fastest is None or pace < fastest:
                            fastest = pace

            splits.append(
                {
                    "distance": round(boundary, 2),
                    "split_distance": round(segment_km, 2),
                    "time": duration,
                    "avg_pace": duration / segment_km if segment_km else None,
                    "max_pace": fastest,
                    "avg_hr": (
                        sum(segment_hr) / len(segment_hr) if segment_hr else None
                    ),
                    "max_hr": max(segment_hr) if segment_hr else None,
                }
            )
            previous = boundary

        return splits
