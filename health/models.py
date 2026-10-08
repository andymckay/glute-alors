"""Tracked health measurements.

A single :class:`Health` row records a person's vitals at a point in time:
weight, blood pressure and resting heart rate.  The bookkeeping fields come
from :class:`core.models.CreatedByModel`.
"""

from django.db import models

from core.models import CreatedByModel


class Health(CreatedByModel):
    """A set of health measurements recorded at one point in time."""

    weight = models.DecimalField(
        "weight (lb)",
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Weight in pounds.",
    )
    systolic = models.PositiveSmallIntegerField(
        "systolic blood pressure",
        null=True,
        blank=True,
        help_text="Systolic blood pressure in mmHg.",
    )
    diastolic = models.PositiveSmallIntegerField(
        "diastolic blood pressure",
        null=True,
        blank=True,
        help_text="Diastolic blood pressure in mmHg.",
    )
    resting_heart_rate = models.PositiveSmallIntegerField(
        "resting heart rate",
        null=True,
        blank=True,
        help_text="Resting heart rate in beats per minute.",
    )
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "health"
        verbose_name_plural = "health"

    def __str__(self):
        recorded = (
            self.created_at.strftime("%Y-%m-%d %H:%M")
            if self.created_at
            else "unsaved"
        )
        return f"Health measurements for {self.created_by or 'Anonymous'} ({recorded})"

    @property
    def blood_pressure(self):
        """Blood pressure formatted as ``systolic/diastolic``, or ``None``."""
        if self.systolic is None or self.diastolic is None:
            return None
        return f"{self.systolic}/{self.diastolic}"
