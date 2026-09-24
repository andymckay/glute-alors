"""Gym exercise catalogue imported from the Fitbod Android app.

The source data lives in ``weights/fitbod/``: JSON:API dumps of the tables the
app itself ships with (``exercises.json`` plus the equipment / muscle / category
lookup and join tables).  ``manage.py import_fitbod_exercises`` joins them and
upserts one :class:`Exercise` per Fitbod exercise, keyed by ``slug``.

Every field below mirrors an attribute of the JSON:API resource, so the names
are Fitbod's rather than ours.  The untouched resource is kept under ``raw``,
which makes the copy lossless.
"""

from django.db import models


class Exercise(models.Model):
    """A single Fitbod exercise."""

    # ------------------------------------------------------------- identity
    fitbod_id = models.CharField(
        "Fitbod id",
        max_length=32,
        unique=True,
        help_text="The JSON:API resource id, e.g. 101.",
    )
    external_resource_id = models.PositiveIntegerField(
        "external resource id",
        null=True,
        blank=True,
        db_index=True,
        help_text="Logged sets reference exercises by this id, not by fitbod_id.",
    )
    name = models.CharField("name", max_length=200, db_index=True)
    slug = models.SlugField(
        "slug",
        max_length=200,
        unique=True,
        help_text="Fitbod's own slug; also the upsert key.",
    )
    alias = models.CharField(
        "alias",
        max_length=200,
        blank=True,
        help_text="Fitbod's single alternate name, when it has one.",
    )

    # ------------------------------------------------------- classification
    level = models.PositiveSmallIntegerField(
        "level",
        null=True,
        blank=True,
        help_text="Fitbod's experience level: 0, 1 or 2.",
    )
    movement_pattern = models.CharField("movement pattern", max_length=40, blank=True)
    mobility_type = models.CharField(
        "mobility type",
        max_length=40,
        blank=True,
        help_text="none, soft_tissue, static_stretch or dynamic_stretch.",
    )
    body_tier = models.PositiveSmallIntegerField("body tier", null=True, blank=True)

    # -------------------------------------------------------------- flags
    is_bodyweight = models.BooleanField("bodyweight", null=True, blank=True)
    is_assisted = models.BooleanField("assisted", null=True, blank=True)
    is_unilateral = models.BooleanField("unilateral", null=True, blank=True)
    is_cardio = models.BooleanField("cardio", null=True, blank=True)
    is_timed = models.BooleanField("timed", null=True, blank=True)
    is_distance = models.BooleanField("distance", null=True, blank=True)
    is_web_published = models.BooleanField(
        "web published",
        null=True,
        blank=True,
        help_text="False/None marks an exercise Fitbod no longer publishes.",
    )

    # ----------------------------------------------------------- taxonomy
    categories = models.JSONField(
        "categories",
        default=list,
        blank=True,
        help_text="Names from exercise_categories, e.g. weighted, hiitTimed.",
    )
    equipment = models.JSONField(
        "equipment", default=list, blank=True, help_text="Names from equipment."
    )
    primary_muscles = models.JSONField("primary muscles", default=list, blank=True)
    secondary_muscles = models.JSONField("secondary muscles", default=list, blank=True)

    # ------------------------------------------------------------ content
    instructions = models.TextField(
        "instructions",
        blank=True,
        help_text="Written instructions, paragraphs separated by a blank line.",
    )
    reference_url = models.URLField(
        "reference url", max_length=500, blank=True, help_text="Fitbod's source."
    )
    image_url = models.CharField(
        "image url",
        max_length=500,
        blank=True,
        help_text="A local path under static/weights, filled in by "
        "fetch_fitbod_images.",
    )
    animation_url = models.URLField("animation url", max_length=500, blank=True)
    video_url = models.URLField("video url", max_length=500, blank=True)

    # ------------------------------------------------------------ ratings
    rating = models.PositiveSmallIntegerField("rating", null=True, blank=True)
    tone_rating = models.PositiveSmallIntegerField("tone rating", null=True, blank=True)
    oly_rating = models.PositiveSmallIntegerField(
        "olympic rating", null=True, blank=True
    )
    tier = models.PositiveSmallIntegerField("tier", null=True, blank=True)
    oly_tier = models.PositiveSmallIntegerField("olympic tier", null=True, blank=True)
    power_tier = models.PositiveSmallIntegerField("power tier", null=True, blank=True)
    relative_weight = models.FloatField("relative weight", null=True, blank=True)
    coefficient = models.PositiveSmallIntegerField(
        "coefficient", null=True, blank=True
    )

    # --------------------------------------------------------- bookkeeping
    raw = models.JSONField(
        "raw",
        default=dict,
        blank=True,
        help_text="The untouched JSON:API resource, so this stays a faithful copy.",
    )
    imported_at = models.DateTimeField("imported at", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "exercise"
        verbose_name_plural = "exercises"

    def __str__(self):
        return self.name
