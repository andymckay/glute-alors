from django.conf import settings
from django.db import models
from django.urls import reverse


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
    notes = models.TextField(blank=True)
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

    class Meta:
        ordering = ["workout_date", "-created_at"]
        verbose_name = "planned workout"
        verbose_name_plural = "planned workouts"

    def __str__(self):
        return f"{self.get_workout_type_display()} on {self.workout_date}"

    def get_absolute_url(self):
        return reverse("alors:planned_workout_detail", args=[str(self.pk)])


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
