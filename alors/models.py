from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
import time

emojis = {
    "run": "🏃‍♀",
    "walk": "🚶",
    "hike": "👢",
    "race": "🏆"
}
 
class PlannedWorkout(models.Model):
    """A workout that has been planned ahead of time."""

    class WorkoutType(models.TextChoices):
        RUN = "run", "Run"
        WALK = "walk", "Walk"
        HIKE = "hike", "Hike"
        RACE = "race", "Race"

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
        help_text="Total planned distance in kilometers.",
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
    notes = models.TextField(blank=True, help_text="Markdown can be used in this field.")
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

    def get_emoji(self):
        return emojis.get(self.workout_type, "")

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

    workout_date = models.DateField("date of the workout")
    total_time = models.DurationField(
        "total time",
        help_text="Total duration, e.g. 00:45:00 (hh:mm:ss).",
    )
    workout_type = models.CharField(
        "type",
        max_length=10,
        choices=PlannedWorkout.WorkoutType.choices,
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
    average_speed = models.DecimalField(
        "average speed (km/h)",
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Average speed in kilometers per hour.",
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
    issues = models.ManyToManyField(
        "Issue",
        verbose_name="issues",
        related_name="workouts",
        blank=True,
        help_text="Issues related to this workout.",
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

    def get_emoji(self):
        return emojis.get(self.workout_type, "")

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
            10: "Max Effort"
        }.get(self.effort, "")

    def get_feeling_as_text(self):
        return {
            5: "Great",
            4: "Good",
            3: "Normal",
            2: "Poor",
            1: "Terrible"
        }.get(self.feeling, "")

class Issue(models.Model):
    """A reported issue or bug to track."""

    title = models.CharField(
        "title",
        max_length=200,
        help_text="A short summary of the issue.",
    )
    text = models.TextField(
        "issue text",
        help_text="Describe the issue in detail; Markdown is supported.",
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
        return time.strftime('%H:%M:%S', time.gmtime(self.summary.get('workout_total_time_seconds', 0)))