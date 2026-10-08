"""Abstract models shared across the project.

They live in their own app so every app can build on the same timestamps and
ownership fields without depending on one another.
"""

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Adds ``created_at`` and ``updated_at`` bookkeeping timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CreatedByModel(TimeStampedModel):
    """A :class:`TimeStampedModel` that also records who created the row."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="created by",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who created this.",
    )

    class Meta:
        abstract = True
