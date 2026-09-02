from django.db import models
from django.urls import reverse


class PlannedWorkout(models.Model):
    """A workout that has been planned ahead of time."""

    class WorkoutType(models.TextChoices):
        RUN = "run", "Run"
        WALK = "walk", "Walk"
        HIKE = "hike", "Hike"
        RACE = "race", "Race"

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
    warm_up = models.TextField(
        "warm up",
        blank=True,
        help_text="Warm-up plan (e.g. distance, drills or time).",
    )
    notes = models.TextField(blank=True)
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
