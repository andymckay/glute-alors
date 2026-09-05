from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import time
import json
from datetime import timedelta


class WorkoutType(models.TextChoices):
    RUN = ["run", "Run"]
    WALK = ["walk", "Walk"]
    HIKE = ["hike", "Hike"]
    STRENGTH = ["strength", "Strength"]
    RECOVERY = ["recovery", "Recovery"]


class PlannedWorkout(models.Model):
    """A workout that has been planned ahead of time."""

    class Status(models.TextChoices):
        DONE = "done", "Done"
        MISSED = "missed", "Missed"
        OVER = "over", "Over"
        UNDER = "under", "Under"

    title = models.CharField(
        "title",
        max_length=200,
        default="",
        help_text="A short name for the workout, e.g. 'Long run'.",
    )
    workout_type = models.CharField(
        "type of workout",
        max_length=10,
        choices=WorkoutType.choices,
        default=WorkoutType.RUN,
    )
    workout_date = models.DateField("date of the workout")
    total_distance = models.DecimalField(
        "total distance (km)",
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total planned distance in kilometers.",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        blank=True,
        default="",
        help_text="Whether the workout was done, missed, over or under.",
    )
    is_race = models.BooleanField(
        "race",
        default=False,
        help_text="Whether this planned workout is a race.",
    )
    warm_up = models.ForeignKey(
        "WarmUp",
        verbose_name="warm up",
        related_name="workouts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The warm-up routine for this workout.",
    )
    notes = models.TextField(
        blank=True, help_text="Markdown can be used in this field."
    )
    comment_count = models.PositiveIntegerField(
        "comment count",
        default=0,
        help_text="Number of comments on this workout.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="planned_workouts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who created this planned workout.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    get_model_name_display = "Planned"

    class Meta:
        ordering = ["workout_date", "-created_at"]
        verbose_name = "planned workout"
        verbose_name_plural = "planned workouts"

    def __str__(self):
        return f"{self.get_workout_type_display()} on {self.workout_date}"

    def get_absolute_url(self):
        return reverse("alors:planned_detail", args=[str(self.pk)])

    def get_date_as_str(self):
        return self.workout_date.strftime("%Y-%m-%d")


class WarmUp(models.Model):
    """A reusable warm-up routine that can be attached to a workout."""

    title = models.CharField(
        "title",
        max_length=200,
        help_text="A short name for the warm-up, e.g. 'Easy jog'.",
    )
    text = models.TextField(
        "warm-up text",
        help_text="The warm-up routine or instructions.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="warmups",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who created this warm-up.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "warm-up"
        verbose_name_plural = "warm-ups"

    def __str__(self):
        return self.title


class Workout(models.Model):
    """A workout that has been completed and recorded."""

    workout_date = models.DateTimeField("date of the workout")
    total_time = models.DurationField(
        "total time",
        help_text="Total duration, e.g. 00:45:00 (hh:mm:ss).",
    )
    workout_type = models.CharField(
        "type",
        max_length=10,
        choices=WorkoutType.choices,
    )
    total_distance = models.DecimalField(
        "total distance (km)",
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total distance covered in kilometers.",
    )
    moving_time = models.DurationField(
        "moving time",
        blank=True,
        null=True,
        help_text="Time spent moving, e.g. 00:44:30 (hh:mm:ss).",
    )
    pace = models.DurationField(
        "pace",
        blank=True,
        null=True,
        help_text="Average pace, e.g. 00:05:30 (hh:mm:ss) per kilometer.",
    )
    effort = models.PositiveSmallIntegerField(
        "effort",
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Rate the effort from 1 (easy) to 10 (all out).",
    )
    feeling = models.PositiveSmallIntegerField(
        "feeling",
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rate how you felt from 1 (poor) to 5 (great).",
    )
    notes = models.TextField(blank=True)
    comment_count = models.PositiveIntegerField(
        "comment count",
        default=0,
        help_text="Number of comments on this workout.",
    )
    workout_source = models.CharField(
        "workout source",
        max_length=200,
        blank=True,
        null=True,
        unique=True,
        help_text="Where this workout came from, e.g. Strava, Garmin, manual.",
    )
    source_url = models.URLField(
        "source url",
        max_length=500,
        blank=True,
        default="",
        help_text="A URL for the original source of this workout.",
    )
    workout_data = models.TextField(
        "workout data",
        blank=True,
        default="",
        help_text="Additional workout data, stored as JSON text.",
    )
    issues = models.ManyToManyField(
        "Issue",
        verbose_name="issues",
        related_name="workouts",
        blank=True,
        help_text="Issues related to this workout.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="workouts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who recorded this workout.",
    )
    get_model_name_display = "Workout"

    class Meta:
        ordering = ["-workout_date"]
        verbose_name = "workout"
        verbose_name_plural = "workouts"

    def __str__(self):
        return f"{self.get_workout_type_display()} on {self.workout_date}"

    def get_absolute_url(self):
        return reverse("alors:workout_detail", args=[str(self.pk)])

    def get_date_as_str(self):
        return self.workout_date.strftime("%Y-%m-%d")

    def get_effort_as_text(self):
        return {
            1: "Very light",
            2: "Light",
            3: "Light",
            4: "Moderate",
            5: "Moderate",
            6: "Moderate",
            7: "Hard",
            8: "Hard",
            9: "Very Hard",
            10: "Max Effort",
        }.get(self.effort, "")

    def get_feeling_as_text(self):
        return {5: "Great", 4: "Good", 3: "Normal", 2: "Poor", 1: "Terrible"}.get(
            self.feeling, ""
        )

    def get_workout_data_as_json(self):
        return json.loads(self.workout_data)

    def _decoded_records(self):
        """Return the ``record_mesgs`` from the decoded FIT data."""
        if not self.workout_data:
            return []
        try:
            data = json.loads(self.workout_data)
        except (ValueError, TypeError):
            return []
        return data.get("record_mesgs") or []

    def _record_series(self, extract, max_points=300):
        """Build ``(seconds, value)`` samples from the FIT records.

        ``extract`` maps a record to a numeric value (or ``None`` to skip it).
        Times are seconds from the first record; if timestamps are unusable the
        value is plotted against the record index instead.
        """
        records = self._decoded_records()
        if not records:
            return []

        from dateutil.parser import isoparse

        samples = []
        start = None
        usable = True
        for record in records:
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
                None
                if record.get("heart_rate") is None
                else int(record["heart_rate"])
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

    def get_route_points(self, max_points=500):
        """Return the workout's GPS track as ``[lat, lon]`` pairs (degrees)."""
        points = []
        for record in self._decoded_records():
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

    def get_splits(self):
        """Return per-kilometre (and lap) splits from the FIT records.

        Each split is a dict with the split's end distance in km, duration in
        seconds, average/max pace (seconds per km) and average/max heart rate.
        Rows are added at every whole kilometre and wherever a recorded lap
        ends, plus a final partial segment up to the total distance.
        """
        records = self._decoded_records()
        if not records:
            return []

        from bisect import bisect_left, bisect_right
        from dateutil.parser import isoparse

        times = []
        kms = []
        heart_rates = []
        record_paces = []
        start = None
        usable = True
        for record in records:
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
            record_paces.append(
                1000.0 / speed if speed and speed > 0 else None
            )

        if not usable or len(times) < 2:
            return []

        total_km = kms[-1]
        if total_km <= 0:
            return []

        # A record interval counts as moving time only when distance advances;
        # stopped periods (e.g. traffic lights) are excluded.
        interval_moving = [0.0]
        for index in range(1, len(kms)):
            if times[index] >= times[index - 1] and kms[index] > kms[index - 1]:
                interval_moving.append(times[index] - times[index - 1])
            else:
                interval_moving.append(0.0)

        # Use the device's own lap markers when the file has them, otherwise
        # fall back to one row per whole kilometre (plus any partial final km).
        try:
            data = json.loads(self.workout_data)
        except (ValueError, TypeError):
            data = {}

        lap_ends = []
        lap_total = 0.0
        for lap in data.get("lap_mesgs") or []:
            length = lap.get("total_distance")
            if not length:
                continue
            lap_total += float(length) / 1000.0
            lap_ends.append(lap_total)

        if lap_ends:
            merged = sorted(
                {
                    round(end, 4)
                    for end in lap_ends
                    if end <= total_km + 0.01
                }
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
            segment_hr = [
                hr for hr in heart_rates[lo:hi] if hr is not None
            ]

            moving_time = sum(interval_moving[lo:hi])
            if moving_time <= 0:
                # No usable distance movement: fall back to elapsed time.
                moving_time = max(0.0, time_at(boundary) - time_at(previous))
            duration = moving_time

            fastest = None
            speed_paces = [
                pace
                for pace in record_paces[lo:hi]
                if pace is not None
            ]
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
                    "time": duration,
                    "avg_pace": duration / segment_km if segment_km else None,
                    "max_pace": fastest,
                    "avg_hr": (
                        sum(segment_hr) / len(segment_hr)
                        if segment_hr
                        else None
                    ),
                    "max_hr": max(segment_hr) if segment_hr else None,
                }
            )
            previous = boundary

        return splits


class Comment(models.Model):
    """A Markdown comment attached to a planned or completed workout."""

    text = models.TextField(
        "comment",
        help_text="Your comment; Markdown is supported.",
    )
    planned_workout = models.ForeignKey(
        "PlannedWorkout",
        verbose_name="planned workout",
        related_name="comments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The planned workout this comment is about.",
    )
    workout = models.ForeignKey(
        "Workout",
        verbose_name="workout",
        related_name="comments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The completed workout this comment is about.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="comments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who wrote this comment.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "comment"
        verbose_name_plural = "comments"

    def __str__(self):
        text = self.text if len(self.text) <= 80 else self.text[:77] + "…"
        return f"{self.created_by or 'Anonymous'}: {text}"


class Issue(models.Model):
    """A reported issue or bug to track."""

    title = models.CharField(
        "title",
        max_length=200,
        help_text="A short summary of the issue.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="issues",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who created this issue.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "issue"
        verbose_name_plural = "issues"

    def __str__(self):
        return self.title


class WeeklySummary(models.Model):
    """A summary of a week, with arbitrary JSON data."""

    date = models.DateField(
        "date",
        help_text="The week this summary relates to (e.g. the Monday).",
    )
    summary = models.JSONField(
        "summary",
        default=dict,
        blank=True,
        help_text="Summary data as JSON.",
    )

    class Meta:
        ordering = ["-date"]
        verbose_name = "weekly summary"
        verbose_name_plural = "weekly summaries"

    def __str__(self):
        return f"Week starting {self.date}"

    def get_date_as_str(self):
        return self.date.strftime("%Y-%m-%d")

    def get_workout_time_as_str(self):
        seconds = self._category_totals("workout")[2]
        return time.strftime("%H:%M:%S", time.gmtime(seconds))


class Label(models.Model):
    """A named, coloured date range used to tag things."""

    class Colour(models.TextChoices):
        PRIMARY = "primary", "Blue"
        SECONDARY = "secondary", "Grey"
        SUCCESS = "success", "Green"
        DANGER = "danger", "Red"
        WARNING = "warning", "Yellow"
        LIGHT = "light", "Light Grey"
        DARK = "dark", "Black"

    title = models.CharField(
        "title",
        max_length=200,
        help_text="A short name for the label.",
    )
    colour = models.CharField(
        "colour",
        max_length=20,
        choices=Colour.choices,
        default=Colour.PRIMARY,
        help_text="A Bootstrap badge colour.",
    )
    start_date = models.DateField("start date")
    end_date = models.DateField("end date")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        related_name="labels",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who created this label.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "title"]
        verbose_name = "label"
        verbose_name_plural = "labels"

    def __str__(self):
        return self.title

    def get_dates_as_list(self):
        result = []
        for k in range(0, 100):
            date = self.start_date + timedelta(days=k)
            if date > self.end_date:
                return result
            result.append(date.strftime("%Y-%m-%d"))
        raise IterationError("Start and end date are more than 100 days apart.")


class NotificationManager(models.Manager):
    """Manager with helpers for per-user notification state."""

    def mark_read_for(self, user, target):
        """Mark a user's notifications about ``target`` as read.

        This covers notifications pointing straight at the planned/completed
        workout as well as notifications about comments left on it (comments
        are shown on the workout's detail page).
        """
        content_type = ContentType.objects.get_for_model(target)
        self.filter(
            recipient=user,
            read=False,
            content_type=content_type,
            object_id=target.pk,
        ).update(read=True)

        if isinstance(target, PlannedWorkout):
            comment_ids = Comment.objects.filter(planned_workout=target).values_list(
                "pk", flat=True
            )
        elif isinstance(target, Workout):
            comment_ids = Comment.objects.filter(workout=target).values_list(
                "pk", flat=True
            )
        else:
            return

        comment_type = ContentType.objects.get_for_model(Comment)
        self.filter(
            recipient=user,
            read=False,
            content_type=comment_type,
            object_id__in=list(comment_ids),
        ).update(read=True)


class Notification(models.Model):
    """Record that a linked model was added or edited."""

    class Action(models.TextChoices):
        ADDED = "added", "Added"
        EDITED = "edited", "Edited"

    # The object the notification is about, e.g. a Comment, PlannedWorkout or
    # Workout, via a generic foreign key.
    content_type = models.ForeignKey(
        ContentType,
        verbose_name="content type",
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField("object id")
    content_object = GenericForeignKey("content_type", "object_id")

    action = models.CharField(
        "action",
        max_length=10,
        choices=Action.choices,
        default=Action.ADDED,
        help_text="What happened to the linked object.",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="actor",
        related_name="notifications_acted",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who performed the action.",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="recipient",
        related_name="notifications",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="The user this notification is for.",
    )
    read = models.BooleanField(
        "read",
        default=False,
        help_text="Whether this notification has been read.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = NotificationManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notification"
        verbose_name_plural = "notifications"

    def __str__(self):
        actor = self.actor or "System"
        return f"{actor} {self.action} {self.content_object}"

    def target(self):
        """The planned/completed workout this notification points at.

        Notifications about comments are resolved to the workout or plan the
        comment was left on.
        """
        obj = self.content_object
        if isinstance(obj, Comment):
            obj = obj.planned_workout or obj.workout
        return obj

    def get_absolute_url(self):
        target = self.target()
        if isinstance(target, PlannedWorkout):
            return reverse("alors:planned_detail", args=[str(target.pk)])
        if isinstance(target, Workout):
            return reverse("alors:workout_detail", args=[str(target.pk)])
        return ""

    def summary(self):
        actor = self.actor or "Someone"
        verb = "added" if self.action == self.Action.ADDED else "edited"
        if isinstance(self.content_object, Comment):
            return f"{actor} {verb} a comment"
        if isinstance(self.content_object, PlannedWorkout):
            return (
                f"{actor} {verb} the planned "
                f"{self.content_object.get_workout_type_display()} workout"
            )
        if isinstance(self.content_object, Workout):
            return (
                f"{actor} {verb} the "
                f"{self.content_object.get_workout_type_display()} workout"
            )
        return f"{actor} {verb} {self.content_object}"


class UserProfile(models.Model):
    """Extra per-user settings, such as their role."""

    class Role(models.TextChoices):
        COACH = "coach", "Coach"
        ATHLETE = "athlete", "Athlete"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="user",
        related_name="profile",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        "role",
        max_length=10,
        choices=Role.choices,
        default=Role.ATHLETE,
        help_text="Whether this user is a coach or an athlete.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user profile"
        verbose_name_plural = "user profiles"

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"
