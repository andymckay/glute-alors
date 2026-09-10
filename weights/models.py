"""Gym exercise catalogue imported from ``weights/exercises/**/exercise.json``."""

from django.db import models


class Force(models.TextChoices):
    PULL = "pull", "Pull"
    PUSH = "push", "Push"
    STATIC = "static", "Static"


class Level(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    EXPERT = "expert", "Expert"


class Mechanic(models.TextChoices):
    COMPOUND = "compound", "Compound"
    ISOLATION = "isolation", "Isolation"


class Equipment(models.TextChoices):
    BODY_ONLY = "body only", "Body only"
    MACHINE = "machine", "Machine"
    OTHER = "other", "Other"
    FOAM_ROLL = "foam roll", "Foam roll"
    KETTLEBELLS = "kettlebells", "Kettlebells"
    DUMBBELL = "dumbbell", "Dumbbell"
    CABLE = "cable", "Cable"
    BARBELL = "barbell", "Barbell"
    BANDS = "bands", "Bands"
    MEDICINE_BALL = "medicine ball", "Medicine ball"
    EXERCISE_BALL = "exercise ball", "Exercise ball"
    EZ_CURL_BAR = "e-z curl bar", "E-Z curl bar"


class Category(models.TextChoices):
    STRENGTH = "strength", "Strength"
    STRETCHING = "stretching", "Stretching"
    PLYOMETRICS = "plyometrics", "Plyometrics"
    STRONGMAN = "strongman", "Strongman"
    POWERLIFTING = "powerlifting", "Powerlifting"
    CARDIO = "cardio", "Cardio"
    OLYMPIC_WEIGHTLIFTING = "olympic weightlifting", "Olympic weightlifting"


class Exercise(models.Model):
    """A gym exercise.

    The fields mirror the JSON keys found in
    ``weights/exercises/<slug>/exercise.json``.
    """

    name = models.CharField("name", max_length=100, unique=True)
    force = models.CharField(
        "force",
        max_length=20,
        choices=Force.choices,
        blank=True,
        null=True,
        help_text="Whether the movement is a push, pull or static hold.",
    )
    level = models.CharField("level", max_length=20, choices=Level.choices)
    mechanic = models.CharField(
        "mechanic",
        max_length=20,
        choices=Mechanic.choices,
        blank=True,
        null=True,
        help_text="Whether the exercise is compound or isolation.",
    )
    equipment = models.CharField(
        "equipment",
        max_length=20,
        choices=Equipment.choices,
        blank=True,
        null=True,
    )
    primary_muscles = models.JSONField(
        "primary muscles", default=list, blank=True
    )
    secondary_muscles = models.JSONField(
        "secondary muscles", default=list, blank=True
    )
    instructions = models.JSONField(
        "instructions", default=list, blank=True
    )
    category = models.CharField(
        "category", max_length=30, choices=Category.choices
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "exercise"
        verbose_name_plural = "exercises"

    def __str__(self):
        return self.name
