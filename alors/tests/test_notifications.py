from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ..models import Comment, Notification, PlannedWorkout, Workout, WorkoutType


class NotificationTests(TestCase):
    def setUp(self):
        self.athlete = User.objects.create_user(username="runner", password="secret123")
        self.coach = User.objects.create_user(username="coach", password="secret123")

    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date(2026, 9, 5),
            "total_distance": Decimal("10.00"),
            "title": "Long run",
            "created_by": self.athlete,
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 4, 8, 30),
            "total_time": timedelta(minutes=50),
            "workout_type": WorkoutType.RUN,
            "created_by": self.athlete,
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def notifications_for(self, user):
        return Notification.objects.filter(recipient=user).order_by("pk")

    def latest_for(self, user):
        return self.notifications_for(user).latest("pk")

    def test_adding_planned_workout_notifies_everyone_except_actor(self):
        planned = self.create_planned()
        self.assertEqual(self.notifications_for(self.coach).count(), 1)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, planned)
        self.assertEqual(notification.actor, self.athlete)

    def test_editing_planned_workout_notifies_others(self):
        planned = self.create_planned()
        # The coach has an unread notification about the plan; once it has
        # been read, a later edit produces a fresh notification again.
        self.notifications_for(self.coach).update(read=True)
        planned.title = "Long run v2"
        planned.save()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, planned)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)

    def test_editing_object_with_unread_notification_adds_no_duplicate(self):
        planned = self.create_planned()
        # The add notification is still unread, so the edit is suppressed.
        planned.title = "Long run v2"
        planned.save()
        self.assertEqual(self.notifications_for(self.coach).count(), 1)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.coach, read=False
            ).count(),
            1,
        )
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, planned)

    def test_adding_workout_notifies_others(self):
        workout = self.create_workout()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, workout)
        self.assertEqual(notification.actor, self.athlete)
        self.assertEqual(self.notifications_for(self.athlete).count(), 0)

    def test_editing_workout_notifies_others(self):
        workout = self.create_workout()
        # The coach's original add notification must be read first so the
        # edit generates a new one.
        self.notifications_for(self.coach).update(read=True)
        workout.notes = "Tough one."
        workout.save()
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, workout)

    def test_actor_is_excluded_and_recorded(self):
        planned = self.create_planned()
        # The coach edits; the coach is excluded and the athlete is notified.
        planned._notification_actor = self.coach
        planned.title = "Edited by coach"
        planned.save()
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.actor, self.coach)
        # The coach's own earlier notification (from the athlete's create) stays.
        self.assertEqual(self.notifications_for(self.coach).count(), 1)

    def test_adding_comment_notifies_others(self):
        planned = self.create_planned()
        comment = Comment.objects.create(
            planned_workout=planned,
            text="Nice session.",
            created_by=self.coach,
        )
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, comment)
        self.assertEqual(notification.actor, self.coach)
        # The coach is not notified about their own comment; their only
        # notification is still the one from the athlete's plan creation.
        self.assertEqual(self.notifications_for(self.coach).count(), 1)

    def test_editing_comment_notifies_others(self):
        planned = self.create_planned()
        comment = Comment.objects.create(
            planned_workout=planned,
            text="Nice session.",
            created_by=self.coach,
        )
        # The athlete has an unread notification about the comment; once it
        # is read, editing the comment produces a fresh notification.
        self.notifications_for(self.athlete).update(read=True)
        comment.text = "Updated comment."
        comment.save()
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, comment)
        self.assertEqual(notification.actor, self.coach)

    def test_editing_comment_while_unread_adds_no_duplicate(self):
        planned = self.create_planned()
        comment = Comment.objects.create(
            planned_workout=planned,
            text="Nice session.",
            created_by=self.coach,
        )
        comment.text = "Updated comment."
        comment.save()
        # The athlete still has only the original, unread notification.
        self.assertEqual(self.notifications_for(self.athlete).count(), 1)
        notification = self.latest_for(self.athlete)
        self.assertEqual(notification.action, "added")
        self.assertEqual(notification.content_object, comment)

    def test_notification_has_read_status_and_timestamps(self):
        self.create_planned()
        notification = self.latest_for(self.coach)
        notification.refresh_from_db()
        self.assertFalse(notification.read)
        self.assertIsNotNone(notification.created_at)
        self.assertIsNotNone(notification.updated_at)

    def test_deleting_linked_object_removes_its_notifications(self):
        planned = self.create_planned()
        content_type = ContentType.objects.get_for_model(planned)
        notifications = Notification.objects.filter(
            content_type=content_type, object_id=planned.pk
        )
        self.assertEqual(notifications.count(), 1)
        planned.delete()
        self.assertFalse(notifications.exists())

    def test_workout_edit_view_claims_owner_and_notifies_others(self):
        self.client.force_login(self.athlete)
        workout = self.create_workout(created_by=None)
        # Without an owner the creation notified everyone; have the coach read
        # it so the edit triggers a fresh notification for them.
        self.notifications_for(self.coach).update(read=True)
        response = self.client.post(
            reverse("alors:workout_edit", args=[workout.pk]),
            {"notes": "Updated via the form."},
        )
        self.assertRedirects(
            response, reverse("alors:workout_detail", args=[workout.pk])
        )
        workout.refresh_from_db()
        self.assertEqual(workout.created_by, self.athlete)
        notification = self.latest_for(self.coach)
        self.assertEqual(notification.action, "edited")
        self.assertEqual(notification.content_object, workout)
        self.assertEqual(notification.actor, self.athlete)

    def test_dedupe_is_checked_per_recipient(self):
        workout = self.create_workout(created_by=None)
        # With no owner set, everyone is notified on creation.
        self.assertEqual(
            Notification.objects.filter(
                recipient__in=[self.athlete, self.coach], read=False
            ).count(),
            2,
        )
        # Only the coach has read their notification.
        self.notifications_for(self.coach).update(read=True)
        workout._notification_actor = self.athlete
        workout.notes = "Updated."
        workout.save()
        # The athlete is the actor (so excluded) and keeps their unread one;
        # the coach read theirs, so they get a fresh notification.
        self.assertEqual(self.notifications_for(self.athlete).count(), 1)
        coach_unread = self.notifications_for(self.coach).filter(read=False)
        self.assertEqual(coach_unread.count(), 1)
        self.assertEqual(coach_unread.first().action, "edited")


class NotificationPageTests(TestCase):
    def setUp(self):
        self.athlete = User.objects.create_user(username="runner", password="secret123")
        self.coach = User.objects.create_user(username="coach", password="secret123")
        self.client.force_login(self.athlete)
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
            created_by=self.athlete,
        )

    def test_empty_page_shows_no_notifications_message(self):
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No notifications yet")

    def test_lists_only_the_logged_in_users_notifications(self):
        # The coach comments on the athlete's plan: the athlete is notified.
        Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<b>coach</b>")
        self.assertContains(response, "added a <b>comment</b>")
        self.assertContains(
            response,
            reverse("alors:planned_detail", args=[self.planned.pk]),
        )
        # The plan's creation only notified the coach, so it is not shown.
        self.assertNotContains(response, "planned run")

    def test_summary_mentions_workout_type_and_links_to_workout(self):
        workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
            created_by=self.athlete,
        )
        # The coach edits the athlete's workout and the athlete is notified.
        workout._notification_actor = self.coach
        workout.notes = "Updated."
        workout.save()
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<b>coach</b>")
        self.assertContains(response, "added a <b>Run</b>")
        self.assertContains(
            response, reverse("alors:workout_detail", args=[workout.pk])
        )

    def test_viewing_planned_workout_marks_comment_notifications_read(self):
        comment = Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        notification = Notification.objects.get(
            recipient=self.athlete, object_id=comment.pk
        )
        self.assertFalse(notification.read)
        self.client.get(reverse("alors:planned_detail", args=[self.planned.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.read)
        # The coach's own notification (about the plan being added) stays unread.
        coach_notification = Notification.objects.get(
            recipient=self.coach, object_id=self.planned.pk
        )
        coach_notification.refresh_from_db()
        self.assertFalse(coach_notification.read)

    def test_viewing_workout_marks_direct_notifications_read(self):
        workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
            created_by=self.athlete,
        )
        workout._notification_actor = self.coach
        workout.notes = "Updated by coach."
        workout.save()
        notification = Notification.objects.get(
            recipient=self.athlete, object_id=workout.pk
        )
        self.assertFalse(notification.read)
        self.client.get(reverse("alors:workout_detail", args=[workout.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.read)

    def test_viewing_object_removes_notification_from_unread_list(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="Nice session!",
            created_by=self.coach,
        )
        self.client.get(reverse("alors:planned_detail", args=[self.planned.pk]))
        response = self.client.get(reverse("alors:notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "added a comment")

    def test_mark_all_as_read_clears_users_notifications(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="One",
            created_by=self.coach,
        )
        Comment.objects.create(
            planned_workout=self.planned,
            text="Two",
            created_by=self.coach,
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            2,
        )
        coach_unread = Notification.objects.filter(
            recipient=self.coach, read=False
        ).count()

        response = self.client.post(reverse("alors:mark_all_notifications_read"))
        self.assertRedirects(response, reverse("alors:notifications"))
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            0,
        )
        # Another user's notifications are not touched.
        self.assertEqual(
            Notification.objects.filter(recipient=self.coach, read=False).count(),
            coach_unread,
        )

    def test_mark_all_read_only_acts_on_post(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="One",
            created_by=self.coach,
        )
        self.client.get(reverse("alors:mark_all_notifications_read"))
        self.assertEqual(
            Notification.objects.filter(recipient=self.athlete, read=False).count(),
            1,
        )


class CleanNotificationsCommandTests(TestCase):
    def setUp(self):
        from django.utils import timezone as django_timezone

        self.now = django_timezone.now()
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            created_by=self.user,
        )

    def notification(self):
        return Notification.objects.create(
            recipient=self.user,
            actor=self.user,
            content_object=self.planned,
        )

    def age(self, notification, days):
        from django.utils import timezone as django_timezone

        Notification.objects.filter(pk=notification.pk).update(
            created_at=django_timezone.now() - timedelta(days=days)
        )

    def test_deletes_notifications_older_than_30_days(self):
        old = self.notification()
        self.age(old, 40)
        recent = self.notification()

        call_command("clean_notifications")

        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recent.pk).exists())

    def test_notifications_just_under_30_days_old_are_kept(self):
        edge = self.notification()
        self.age(edge, 29)

        call_command("clean_notifications")

        self.assertTrue(Notification.objects.filter(pk=edge.pk).exists())

    def test_days_option_changes_the_cutoff(self):
        kept = self.notification()
        self.age(kept, 20)
        removed = self.notification()
        self.age(removed, 40)

        call_command("clean_notifications", "--days", 30)

        self.assertFalse(Notification.objects.filter(pk=removed.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=kept.pk).exists())
