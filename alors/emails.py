"""The body of the daily email.

Kept out of ``views.py`` so both the ``debug/email`` preview view and the
``send_daily_emails`` management command can build it without either importing
the other.
"""

from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse


def _comment_target(comment):
    """The planned, completed or weights workout a comment was left on."""
    return comment.planned_workout or comment.workout or comment.weights_workout


def _comment_url(comment):
    """Where the recipient can read a comment."""
    from .models import PlannedWorkout, Workout
    from weights.models import WeightsWorkout

    target = _comment_target(comment)
    if isinstance(target, PlannedWorkout):
        return f"{reverse('alors:edit_planned', args=[target.pk])}#comments"
    if isinstance(target, Workout):
        return f"{reverse('alors:workout_detail', args=[target.pk])}#comments"
    if isinstance(target, WeightsWorkout):
        return f"{reverse('weights:workout_perform', args=[target.pk])}#comments"
    return ""


def comment_email_as_text(comment, recipient):
    """The body of the email sent to ``recipient`` about a new comment."""
    return render_to_string(
        "comment_email.txt",
        {
            "recipient": recipient,
            "comment": comment,
            "target": _comment_target(comment),
            "comment_url": _comment_url(comment),
            "host": settings.HOST,
        },
    )


def email_as_text(user):
    """What ``user`` has not seen yet, or ``None`` when there is nothing to say.

    Rendered from ``templates/email.txt``, so a user is sent exactly what the
    preview page shows them.  Callers decide what "nothing to say" means:
    ``email_html`` renders it anyway, ``send_daily_emails`` skips the user.
    """
    notifications = user.notifications.filter(read=False)
    if not notifications:
        return None

    return render_to_string(
        "email.txt",
        {
            "user": user,
            "notifications": notifications,
            "host": settings.HOST,
        },
    )
