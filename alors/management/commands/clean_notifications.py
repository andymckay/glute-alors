"""Delete notifications that are older than 30 days."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from alors.models import Notification


class Command(BaseCommand):
    help = "Delete all notifications that are more than 30 days old."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete notifications older than this many days " "(default: 30).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} notification(s) older than {days} days."
            )
        )
