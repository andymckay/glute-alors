"""Signals that keep WeeklySummary records and Notifications in sync."""

import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.db.models import F
from django.db.models.signals import post_delete, post_save, pre_save
from django.utils.dateparse import parse_date

from .emails import comment_email_as_text
from .models import (
    Comment,
    Notification,
    PlannedWorkout,
    Status,
    UserProfile,
    WeeklySummary,
    Workout,
    WorkoutType,
)

logger = logging.getLogger(__name__)


def _as_date(value):
    """Coerce a date, a datetime, or a 'YYYY-MM-DD' string to a date."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return parse_date(str(value))


def _sunday_for(workout_date):
    """Return the Sunday of the week that contains ``workout_date``."""
    workout_date = _as_date(workout_date)
    return workout_date + datetime.timedelta(days=6 - workout_date.weekday())


def _by_type(queryset, with_time=False):
    """Group items by workout type.

    Returns a dict like ``{"run": {"workouts": 2, "total_distance": 10.0,
    "total_time": 1800}}``. ``total_time`` is in seconds and is only
    populated when ``with_time`` is true (completed workouts have a time;
    planned workouts do not).
    """
    grouped = {}
    for item in queryset:
        key = item.workout_type
        entry = grouped.setdefault(
            key,
            {"workouts": 0, "total_distance": 0.0, "total_time": 0},
        )
        entry["workouts"] += 1
        entry["total_distance"] += float(item.total_distance or 0)
        if with_time:
            time_value = item.total_time
            if time_value is not None:
                entry["total_time"] += int(time_value.total_seconds())

    for entry in grouped.values():
        entry["total_distance"] = round(entry["total_distance"], 2)
    return grouped


def _effort_feeling(queryset):
    """Return each completed workout's effort and feeling, in date order.

    A flat list, deliberately not grouped by workout type::

        [{"workout_type": "run", "effort": 6, "feeling": 4}, ...]

    An unrated effort or feeling stays ``None``.
    """
    return [
        {
            "workout_type": workout.workout_type,
            "effort": workout.effort,
            "feeling": workout.feeling,
        }
        for workout in queryset.order_by("workout_date_for_timezone", "pk")
    ]


def refresh_weekly_summary(sunday, user_id):
    """Recompute one user's summary for the week ending on ``sunday``.

    Planned and completed workouts are each aggregated by workout type:

    ``{"planned_workout": {"run": {"total_distance": 10.0, "total_time": 0}},
       "workout": {"run": {"total_distance": 10.0, "total_time": 1800}},
       "effort_feeling": [{"workout_type": "run", "effort": 6,
                           "feeling": 4}]}``
    """
    if user_id is None:
        return
    week_start = sunday - datetime.timedelta(days=6)

    planned = PlannedWorkout.objects.filter(
        created_by_id=user_id,
        workout_date__gte=week_start,
        workout_date__lte=sunday,
    )
    completed = Workout.objects.filter(
        created_by_id=user_id,
        workout_date_for_timezone__date__gte=week_start,
        workout_date_for_timezone__date__lte=sunday,
    )

    if not planned.exists() and not completed.exists():
        # Nothing remains for that week, so drop this user's summary.
        WeeklySummary.objects.filter(date=sunday, created_by_id=user_id).delete()
        return
    summary = {
        "planned_workout": _by_type(planned),
        "workout": _by_type(completed, with_time=True),
        "effort_feeling": _effort_feeling(completed),
    }
    WeeklySummary.objects.update_or_create(
        date=sunday,
        created_by_id=user_id,
        defaults={"summary": summary},
    )


def _remember_original_date(sender, instance, **kwargs):
    """Stash the previous date and owner so edits refresh both summaries."""
    instance._original_workout_date = None
    instance._original_created_by_id = None
    if instance.pk is not None:
        value = "workout_date" if instance.is_planned else "workout_date_for_timezone"
        original = (
            type(instance)
            .objects.filter(pk=instance.pk)
            .values_list(value, "created_by_id")
            .first()
        )
        if original is not None:
            instance._original_workout_date, instance._original_created_by_id = original


def _sync_weekly_summary(sender, instance, **kwargs):
    """Create or update the summaries for the workout's owner and week(s)."""
    value = "workout_date" if instance.is_planned else "workout_date_for_timezone"
    workout_date = getattr(instance, value, None) or instance.workout_date
    sundays = {_sunday_for(workout_date)}
    original = getattr(instance, "_original_workout_date", None)
    if original is not None:
        sundays.add(_sunday_for(original))

    user_ids = {instance.created_by_id}
    original_user_id = getattr(instance, "_original_created_by_id", None)
    if original_user_id is not None:
        user_ids.add(original_user_id)

    for sunday in sundays:
        for user_id in user_ids:
            refresh_weekly_summary(sunday, user_id)


def _sync_weekly_summary_on_delete(sender, instance, **kwargs):
    """Refresh the owner's weekly summary after a workout is deleted."""
    value = "workout_date" if instance.is_planned else "workout_date_for_timezone"
    workout_date = getattr(instance, value, None) or instance.workout_date
    if workout_date is not None:
        refresh_weekly_summary(_sunday_for(workout_date), instance.created_by_id)


for _model in (PlannedWorkout, Workout):
    pre_save.connect(
        _remember_original_date,
        sender=_model,
        dispatch_uid=f"weekly_pre_save_{_model.__name__}",
    )
    post_save.connect(
        _sync_weekly_summary,
        sender=_model,
        dispatch_uid=f"weekly_post_save_{_model.__name__}",
    )
    post_delete.connect(
        _sync_weekly_summary_on_delete,
        sender=_model,
        dispatch_uid=f"weekly_post_delete_{_model.__name__}",
    )


def _notify_on_save(sender, instance, created, **kwargs):
    """Notify the users the actor has shared their profile with.

    Only the actor's visibility list receives notifications, and the actor is
    never notified about their own change. With no actor or an empty list,
    nobody is notified.

    A user only ever has one unread notification per object: if they already
    have an unread notification about ``instance``, no further notification is
    added for them until they read the existing one.
    """
    actor = getattr(instance, "_notification_actor", None)
    if actor is None:
        actor = getattr(instance, "created_by", None)
    if actor is None:
        return
    try:
        recipients = actor.profile.visibility.exclude(pk=actor.pk)
    except UserProfile.DoesNotExist:
        return
    action = Notification.Action.ADDED if created else Notification.Action.EDITED

    # Drop any recipient that already has an unread notification about this
    # object, so people are not spammed with duplicates for the same thing.
    content_type = ContentType.objects.get_for_model(instance)
    already_notified = Notification.objects.filter(
        read=False,
        content_type=content_type,
        object_id=instance.pk,
        recipient__in=recipients,
    ).values_list("recipient_id", flat=True)
    recipients = recipients.exclude(pk__in=already_notified)

    Notification.objects.bulk_create(
        [
            Notification(
                content_object=instance,
                action=action,
                actor=actor,
                recipient=recipient,
            )
            for recipient in recipients
        ]
    )

    if created and isinstance(instance, Comment):
        _email_comment_subscribers(instance)


def _email_comment_subscribers(comment):
    """Email the users who can see a new comment, except its author."""
    from .utils import visible_users

    if comment.created_by_id is None:
        return
    audience = visible_users(comment.created_by).exclude(pk=comment.created_by_id)
    subscribers = audience.filter(
        is_active=True, profile__send_comment_email=True
    ).exclude(email="")
    for recipient in subscribers:
        try:
            send_mail(
                "New comment on Glute Alors",
                comment_email_as_text(comment, recipient),
                settings.DEFAULT_FROM_EMAIL,
                [recipient.email],
            )
        except Exception:
            logger.exception(
                "Could not email %s about comment %s",
                recipient.email,
                comment.pk,
            )


def _remove_notifications(sender, instance, **kwargs):
    """Delete notifications pointing at a linked object being removed."""
    content_type = ContentType.objects.get_for_model(instance)
    Notification.objects.filter(
        content_type=content_type,
        object_id=instance.pk,
    ).delete()


for _model in (Comment, PlannedWorkout, Workout):
    post_save.connect(
        _notify_on_save,
        sender=_model,
        dispatch_uid=f"notify_post_save_{_model.__name__}",
    )
    post_delete.connect(
        _remove_notifications,
        sender=_model,
        dispatch_uid=f"notify_post_delete_{_model.__name__}",
    )


def _comment_parent(instance):
    """Return the planned/completed workout a comment is attached to."""
    from weights.models import WeightsWorkout

    try:
        return (
            instance.planned_workout
            or instance.workout
            or instance.weights_workout
        )
    except (
        PlannedWorkout.DoesNotExist,
        Workout.DoesNotExist,
        WeightsWorkout.DoesNotExist,
    ):
        # The parent has already been deleted (e.g. cascade delete).
        return None


def _adjust_comment_count(parent, delta):
    if parent is None:
        return
    parent.__class__.objects.filter(pk=parent.pk).update(
        comment_count=F("comment_count") + delta
    )


def _sync_comment_count_on_save(sender, instance, created, **kwargs):
    """Increment the parent's comment_count when a comment is added."""
    if created:
        _adjust_comment_count(_comment_parent(instance), 1)


def _sync_comment_count_on_delete(sender, instance, **kwargs):
    """Decrement the parent's comment_count when a comment is removed."""
    _adjust_comment_count(_comment_parent(instance), -1)


post_save.connect(
    _sync_comment_count_on_save,
    sender=Comment,
    dispatch_uid="comment_count_post_save_Comment",
)
post_delete.connect(
    _sync_comment_count_on_delete,
    sender=Comment,
    dispatch_uid="comment_count_post_delete_Comment",
)


def _sync_planned_status_from_workout(sender, instance, created, **kwargs):
    """Set a planned workout's status when its workout is added.

    The distances of every actual workout of the same type on the same day are
    summed and compared with the single planned workout for that type and day:

    * within 20% of the plan -> done
    * more than 20% under the plan -> under
    * more than 20% over the plan -> over
    """
    workout_date = _as_date(instance.workout_date_for_timezone or instance.workout_date)
    planned = PlannedWorkout.objects.filter(
        workout_date=workout_date,
        workout_type=instance.workout_type,
    )
    # Only update when there's one unambiguous plan for that type and day.
    if planned.count() != 1:
        return
    planned = planned.first()
    if planned.total_distance is None:
        return

    actual_total = sum(
        (
            actual.total_distance
            for actual in Workout.objects.filter(
                workout_date_for_timezone__date=workout_date,
                workout_type=instance.workout_type,
                total_distance__isnull=False,
            )
        ),
        Decimal("0"),
    )

    planned_distance = planned.total_distance
    margin = planned_distance * Decimal("0.20")
    if abs(actual_total - planned_distance) <= margin:
        status = Status.DONE
    elif actual_total < planned_distance:
        status = Status.UNDER
    else:
        status = Status.OVER

    if planned.status != status:
        PlannedWorkout.objects.filter(pk=planned.pk).update(status=status)


post_save.connect(
    _sync_planned_status_from_workout,
    sender=Workout,
    dispatch_uid="planned_status_post_save_Workout",
)
