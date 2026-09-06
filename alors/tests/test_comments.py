from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import Comment, PlannedWorkout, Workout, WorkoutType


class CommentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="commenter", password="secret123")
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
            created_by=self.user,
        )
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
        )

    def comment(self, **overrides):
        values = {"text": "Nice session.", "created_by": self.user}
        values.update(overrides)
        return Comment.objects.create(**values)

    def test_comment_can_attach_to_planned_workout(self):
        comment = self.comment(planned_workout=self.planned)
        self.assertEqual(self.planned.comments.count(), 1)
        self.assertEqual(self.planned.comments.first(), comment)

    def test_comment_can_attach_to_workout(self):
        comment = self.comment(workout=self.workout)
        self.assertEqual(self.workout.comments.count(), 1)
        self.assertEqual(self.workout.comments.first(), comment)

    def test_multiple_comments_allowed(self):
        self.comment(planned_workout=self.planned, text="First.")
        self.comment(planned_workout=self.planned, text="Second.")
        self.assertEqual(self.planned.comments.count(), 2)

    def test_timestamps_are_set(self):
        comment = self.comment(workout=self.workout)
        comment.refresh_from_db()
        self.assertIsNotNone(comment.created_at)
        self.assertIsNotNone(comment.updated_at)

    def test_created_by_links_back_to_user(self):
        self.comment(planned_workout=self.planned)
        self.assertEqual(self.user.comments.count(), 1)

    def test_deleting_parent_deletes_comments(self):
        comment = self.comment(planned_workout=self.planned)
        self.planned.delete()
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_comment_count_starts_at_zero(self):
        self.assertEqual(self.planned.comment_count, 0)
        self.assertEqual(self.workout.comment_count, 0)

    def test_comment_count_increments_when_comment_added(self):
        self.comment(planned_workout=self.planned)
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 1)

        self.comment(workout=self.workout)
        self.comment(workout=self.workout)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.comment_count, 2)

    def test_comment_count_decrements_when_comment_removed(self):
        comment = self.comment(planned_workout=self.planned)
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 1)
        comment.delete()
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.comment_count, 0)


class CommentViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="commenter", password="secret123")
        self.client.force_login(self.user)
        self.planned = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 5),
            total_distance=Decimal("10.00"),
            title="Long run",
        )
        self.workout = Workout.objects.create(
            workout_date=datetime(2026, 9, 4, 8, 30),
            total_time=timedelta(minutes=50),
            workout_type=WorkoutType.RUN,
        )

    def test_add_comment_to_planned_workout(self):
        response = self.client.post(
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
            {"text": "Looking **good**!"},
        )
        self.assertRedirects(
            response, reverse("alors:planned_detail", args=[self.planned.pk])
        )
        comment = Comment.objects.get(planned_workout=self.planned)
        self.assertEqual(comment.text, "Looking **good**!")
        self.assertEqual(comment.created_by, self.user)

    def test_add_comment_to_workout(self):
        response = self.client.post(
            reverse("alors:add_workout_comment", args=[self.workout.pk]),
            {"text": "Felt great!"},
        )
        self.assertRedirects(
            response, reverse("alors:workout_detail", args=[self.workout.pk])
        )
        comment = Comment.objects.get(workout=self.workout)
        self.assertEqual(comment.text, "Felt great!")
        self.assertEqual(comment.created_by, self.user)

    def test_blank_comment_is_rejected(self):
        response = self.client.post(
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
            {"text": ""},
        )
        self.assertRedirects(
            response, reverse("alors:planned_detail", args=[self.planned.pk])
        )
        self.assertFalse(Comment.objects.filter(planned_workout=self.planned).exists())

    def test_planned_detail_page_shows_comments_and_form(self):
        Comment.objects.create(
            planned_workout=self.planned,
            text="**great** run",
            created_by=self.user,
        )
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.planned.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<strong>great</strong>")
        self.assertContains(response, "Add a comment")
        self.assertContains(
            response,
            reverse("alors:add_planned_comment", args=[self.planned.pk]),
        )

    def test_workout_detail_page_shows_comments_and_form(self):
        Comment.objects.create(
            workout=self.workout, text="Nice session", created_by=self.user
        )
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nice session")
        self.assertContains(response, "Add a comment")
        self.assertContains(
            response,
            reverse("alors:add_workout_comment", args=[self.workout.pk]),
        )
