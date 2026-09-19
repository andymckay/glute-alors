from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import SavedWorkout


class SavedWorkoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.saved_workout = SavedWorkout.objects.create(
            title="Easy jog",
            text="Jog slowly for five minutes.",
            created_by=self.user,
        )

    def test_list_shows_saved_workouts(self):
        response = self.client.get(reverse("alors:saved_workout_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Easy jog")
        self.assertContains(response, reverse("alors:saved_workout_add"))

    def test_add_sets_created_by_and_redirects(self):
        response = self.client.post(
            reverse("alors:saved_workout_add"),
            {"title": "Strides", "text": "Six short strides."},
        )
        self.assertRedirects(response, reverse("alors:saved_workout_list"))
        saved_workout = SavedWorkout.objects.get(title="Strides")
        self.assertEqual(saved_workout.created_by, self.user)

    def test_edit_updates_saved_workout(self):
        url = reverse("alors:saved_workout_edit", args=[self.saved_workout.pk])
        response = self.client.post(
            url,
            {"title": "Easy jog & drills", "text": "Updated routine."},
        )
        self.assertRedirects(response, reverse("alors:saved_workout_list"))
        self.saved_workout.refresh_from_db()
        self.assertEqual(self.saved_workout.title, "Easy jog & drills")
        self.assertEqual(self.saved_workout.text, "Updated routine.")

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(
            reverse("alors:saved_workout_edit", args=[self.saved_workout.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.saved_workout.title)

    def test_delete_removes_saved_workout(self):
        response = self.client.post(
            reverse("alors:saved_workout_delete", args=[self.saved_workout.pk])
        )
        self.assertRedirects(response, reverse("alors:saved_workout_list"))
        self.assertFalse(
            SavedWorkout.objects.filter(pk=self.saved_workout.pk).exists()
        )
