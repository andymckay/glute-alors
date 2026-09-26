"""Tests for the send_daily_emails management command."""

from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from ..management.commands import send_daily_emails
from ..models import PlannedWorkout, UserProfile, WorkoutType


class SendDailyEmailsCommandTests(TestCase):
    """Django's test runner swaps in the locmem backend, which fills mail.outbox."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="coach", password="secret123", email="coach@example.com"
        )
        self.athlete = User.objects.create_user(
            username="runner", password="secret123", email="runner@example.com"
        )

    def subscribe(self, user, send_daily_email=True):
        UserProfile.objects.create(user=user, send_daily_email=send_daily_email)

    def leave_something_to_say(self, author, day):
        """A planned workout notifies everyone except whoever created it."""
        PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, day),
            title="Long run",
            created_by=author,
        )

    def test_emails_a_subscribed_user(self):
        self.subscribe(self.athlete)
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["runner@example.com"])
        self.assertEqual(message.subject, send_daily_emails.SUBJECT)
        self.assertIn("Long run", message.body)
        # The body is the email.txt template, the one the preview page shows.
        self.assertIn("Turn off email here", message.body)

    def test_skips_users_without_a_profile(self):
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_skips_a_profile_with_the_box_unticked(self):
        self.subscribe(self.athlete, send_daily_email=False)
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_skips_superusers_even_when_subscribed(self):
        admin = User.objects.create_superuser(
            username="admin", password="secret123", email="admin@example.com"
        )
        self.subscribe(admin)
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_skips_a_subscriber_with_nothing_to_say(self):
        self.subscribe(self.athlete)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_skips_users_without_an_email_address(self):
        without = User.objects.create_user(username="noemail", password="secret123")
        self.subscribe(without)
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_skips_deactivated_users(self):
        gone = User.objects.create_user(
            username="gone",
            password="secret123",
            email="gone@example.com",
            is_active=False,
        )
        self.subscribe(gone)
        self.leave_something_to_say(self.coach, 5)

        call_command("send_daily_emails")

        self.assertEqual(mail.outbox, [])

    def test_a_failing_send_does_not_stop_the_others(self):
        self.subscribe(self.coach)
        self.subscribe(self.athlete)
        self.leave_something_to_say(self.coach, 5)  # the athlete has news
        self.leave_something_to_say(self.athlete, 6)  # and so does the coach

        real_send_mail = mail.send_mail
        attempts = []

        def flaky(*args, **kwargs):
            attempts.append(args)
            if len(attempts) == 1:
                raise RuntimeError("mailbox unavailable")
            return real_send_mail(*args, **kwargs)

        with mock.patch.object(send_daily_emails, "send_mail", side_effect=flaky):
            call_command("send_daily_emails")

        self.assertEqual(len(attempts), 2)  # it carried on past the failure
        self.assertEqual(len(mail.outbox), 1)  # and the other email arrived
