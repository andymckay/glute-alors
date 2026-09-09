"""Signals that keep WeeklySummary records and Notifications in sync."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.utils.dateparse import parse_date
from .models import (
    Comment,
    Notification,
    PlannedWorkout,
    Status,
    WeeklySummary,
    Workout,
    WorkoutType,
)

User = get_user_model()


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


def refresh_weekly_summary(sunday):
    """Recompute and store the weekly summary for the week ending on ``sunday``.

    Planned and completed workouts are each aggregated by workout type:

    ``{"planned_workout": {"run": {"total_distance": 10.0, "total_time": 0}},
       "workout": {"run": {"total_distance": 10.0, "total_time": 1800}}}``
    """
    week_start = sunday - datetime.timedelta(days=6)

    planned = PlannedWorkout.objects.filter(
        workout_date__gte=week_start,
        workout_date__lte=sunday,
    )
    completed = Workout.objects.filter(
        workout_date__date__gte=week_start,
        workout_date__date__lte=sunday,
    )

    if not planned.exists() and not completed.exists():
        # Nothing remains for that week, so drop the summary.
        WeeklySummary.objects.filter(date=sunday).delete()
        return
    summary = {
        "planned_workout": _by_type(planned),
        "workout": _by_type(completed, with_time=True),
    }
    WeeklySummary.objects.update_or_create(
        date=sunday,
        defaults={"summary": summary},
    )


def _remember_original_date(sender, instance, **kwargs):
    """Stash the previous date so moved workouts can refresh both weeks."""
    instance._original_workout_date = None
    if instance.pk is not None:
        original = (
            type(instance)
            .objects.filter(pk=instance.pk)
            .values_list("workout_date", flat=True)
            .first()
        )
        instance._original_workout_date = original


def _should_sync_workout(instance):
    """Only completed ``run`` workouts contribute to the weekly summary."""
    return getattr(instance, "workout_type", None) == WorkoutType.RUN


def _sync_weekly_summary(sender, instance, **kwargs):
    """Create or update weekly summaries for the workout's week(s)."""
    if sender is Workout and not _should_sync_workout(instance):
        return

    sundays = {_sunday_for(instance.workout_date)}
    original = getattr(instance, "_original_workout_date", None)
    if original is not None:
        sundays.add(_sunday_for(original))

    for sunday in sundays:
        refresh_weekly_summary(sunday)


def _sync_weekly_summary_on_delete(sender, instance, **kwargs):
    """Refresh the weekly summary after a workout is deleted."""
    if sender is Workout and not _should_sync_workout(instance):
        return

    workout_date = getattr(instance, "workout_date", None)
    if workout_date is not None:
        refresh_weekly_summary(_sunday_for(workout_date))


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
    """Notify every user except the actor when a linked model is added/edited.

    A user only ever has one unread notification per object: if they already
    have an unread notification about ``instance``, no further notification is
    added for them until they read the existing one.
    """
    actor = getattr(instance, "_notification_actor", None)
    if actor is None:
        actor = getattr(instance, "created_by", None)
    action = Notification.Action.ADDED if created else Notification.Action.EDITED

    # Also exclude super users.
    recipients = (
        User.objects.exclude(Q(pk=actor.pk) | Q(is_superuser=True))
        if actor
        else User.objects.all()
    )

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
    try:
        return instance.planned_workout or instance.workout
    except (PlannedWorkout.DoesNotExist, Workout.DoesNotExist):
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

    * within 10% of the plan -> done
    * more than 10% under the plan -> under
    * more than 10% over the plan -> over
    """
    if not created:
        return

    workout_date = _as_date(instance.workout_date)
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
                workout_date__date=workout_date,
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
