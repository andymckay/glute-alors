"""The body of the daily email.

Kept out of ``views.py`` so both the ``debug/email`` preview view and the
``send_daily_emails`` management command can build it without either importing
the other.
"""

from django.conf import settings
from django.template.loader import render_to_string


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
