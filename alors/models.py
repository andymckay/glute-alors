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
from bisect import bisect_left, bisect_right
from dateutil.parser import isoparse
from parsers.fit import Fit, NullParser


class WorkoutType(models.TextChoices):
    RUN = ["run", "Run"]
    WALK = ["walk", "Walk"]
    HIKE = ["hike", "Hike"]
    STRENGTH = ["strength", "Strength"]
    RECOVERY = ["recovery", "Recovery"]
    OTHER = ["other", "Other"]


class Colour(models.TextChoices):
    """Bootstrap badge colours, shared by ``Label`` and ``Issue``."""

    PRIMARY = "primary", "Blue"
    SECONDARY = "secondary", "Grey"
    SUCCESS = "success", "Green"
    DANGER = "danger", "Red"
    WARNING = "warning", "Yellow"
    LIGHT = "light", "Light Grey"
    DARK = "dark", "Black"


class Status(models.TextChoices):
    DONE = "done", "Done"
    MISSED = "missed", "Missed"
    OVER = "over", "Over"
    UNDER = "under", "Under"


class PlannedWorkout(models.Model):
    """A workout that has been planned ahead of time."""

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
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

    def get_workout_data(self):
        if not self.workout_data:
            return NullParser()
        try:
            return Fit(json.loads(self.workout_data))
        except (ValueError, TypeError):
            return NullParser()


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
    colour = models.CharField(
        "colour",
        max_length=20,
        choices=Colour.choices,
        default=Colour.PRIMARY,
        help_text="A Bootstrap badge colour.",
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

    Colour = Colour  # module-level choices shared with Issue

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

    def summary(self):
        actor = self.actor or "Someone"
        verb = "added" if self.action == self.Action.ADDED else "edited"
        object_name = ""
        iscomment = False
        if isinstance(self.content_object, Comment):
            object_name = "comment"
            iscomment = True
        else:
            object_name = self.content_object.get_workout_type_display()
        return {
            "actor": actor,
            "verb": verb,
            "object_name": object_name,
            "is_comment": iscomment,
        }


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
    avatar = models.FileField(
        "profile image",
        upload_to="avatars/",
        blank=True,
        null=True,
        help_text="An image shown next to your name.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user profile"
        verbose_name_plural = "user profiles"

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"
