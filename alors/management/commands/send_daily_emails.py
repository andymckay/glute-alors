"""Email every subscribed user a digest of what they have not seen yet.

The body is built by ``alors.emails.email_as_text``, so it is the same
``templates/email.txt`` that the ``debug/email`` page previews.  Anyone with
nothing new is skipped rather than sent an empty digest.

Intended for cron, alongside the other daily jobs in ``glute/crontab``.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from alors.emails import email_as_text

User = get_user_model()

#: Subject line of the daily email.
SUBJECT = "Glute Alors daily update"


class Command(BaseCommand):
    help = (
        "Send the daily email to every non-superuser whose profile asks for "
        "one. Users with nothing new are skipped."
    )

    def handle(self, *args, **options):
        # Someone only gets mail if they asked for it and can actually receive
        # it, so superusers, deactivated accounts and blank addresses are out.
        recipients = (
            User.objects.filter(
                is_superuser=False,
                is_active=True,
                profile__send_daily_email=True,
            )
            .exclude(email="")
            .order_by("username")
        )

        sent = 0
        skipped = 0
        failed = []

        for user in recipients:
            body = email_as_text(user)
            if not body:
                # Nothing has happened that they have not already seen.
                skipped += 1
                continue

            # One unreachable address must not cost everyone else their email,
            # so a failure is collected and reported rather than raised.
            try:
                send_mail(SUBJECT, body, settings.DEFAULT_FROM_EMAIL, [user.email])
            except Exception as error:
                failed.append(f"{user.email}: {error}")
                continue
            sent += 1

        for item in failed:
            self.stderr.write(self.style.WARNING(f"Could not email {item}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {sent} email(s) sent, {skipped} skipped with nothing to "
                f"say, {len(failed)} failed."
            )
        )
