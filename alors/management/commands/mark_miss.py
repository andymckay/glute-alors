"""Mark past-due planned workouts without a status as missed."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from alors.models import PlannedWorkout, Status


class Command(BaseCommand):
    help = (
        "Set the status of planned workouts that are in the past and have no "
        "status yet to 'missed'."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        missed = (
            PlannedWorkout.objects.filter(workout_date__lt=today, status="")
            .exclude(workout_type="recovery")
            .exclude(workout_type="other")
            .update(status=Status.MISSED)
        )
        self.stdout.write(
            self.style.SUCCESS(f"Marked {missed} planned workout(s) as missed.")
        )
