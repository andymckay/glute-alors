from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import PlannedWorkout, WorkoutType


class LoggedOutViewTests(TestCase):
    """Workout views must not be usable by a logged-out user.

    Every @login_required view should respond with a redirect to the
    login page (carrying the requested URL as the ``next`` parameter)
    when the user is not authenticated.
    """

    def setUp(self):
        self.workout = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-02",
            total_distance="10.00",
        )

    def assert_login_required(self, method, url):
        response = getattr(self.client, method)(url)
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        self.assertEqual(parsed.path, "/", "should redirect to the login page")
        self.assertEqual(parse_qs(parsed.query).get("next"), [url])

    def test_logout_requires_login(self):
        url = reverse("alors:logout")
        self.assert_login_required("get", url)

    def test_profile_requires_login(self):
        url = reverse("alors:profile")
        self.assert_login_required("get", url)

    def test_notifications_requires_login(self):
        url = reverse("alors:notifications")
        self.assert_login_required("get", url)

    def test_mark_all_notifications_read_requires_login(self):
        url = reverse("alors:mark_all_notifications_read")
        self.assert_login_required("post", url)

    def test_calendar_requires_login(self):
        url = reverse("alors:calendar")
        self.assert_login_required("get", url)

    def test_add_planned_workout_requires_login(self):
        url = reverse("alors:add_planned")
        self.assert_login_required("get", url)

    def test_planned_workout_detail_requires_login(self):
        url = reverse("alors:planned_detail", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_edit_planned_workout_requires_login(self):
        url = reverse("alors:edit_planned", args=[self.workout.pk])
        self.assert_login_required("get", url)

    def test_delete_planned_workout_requires_login(self):
        url = reverse("alors:delete_planned", args=[self.workout.pk])
        self.assert_login_required("post", url)

    def test_workout_is_not_deleted_by_anonymous_delete(self):
        """An anonymous POST to delete must not delete the workout."""
        url = reverse("alors:delete_planned", args=[self.workout.pk])
        self.assert_login_required("post", url)
        self.assertTrue(PlannedWorkout.objects.filter(pk=self.workout.pk).exists())

    def test_planned_workout_webcal_is_publicly_available(self):
        # The ICS feed is intentionally public so calendar apps can subscribe.
        response = self.client.get(reverse("alors:planned_webcal"))
        self.assertEqual(response.status_code, 200)

    def test_warmup_list_requires_login(self):
        url = reverse("alors:warmup_list")
        self.assert_login_required("get", url)

    def test_warmup_add_requires_login(self):
        url = reverse("alors:warmup_add")
        self.assert_login_required("get", url)

    def test_warmup_edit_requires_login(self):
        url = reverse("alors:warmup_edit", args=[1])
        self.assert_login_required("get", url)

    def test_warmup_delete_requires_login(self):
        url = reverse("alors:warmup_delete", args=[1])
        self.assert_login_required("post", url)

    def test_workout_detail_requires_login(self):
        url = reverse("alors:workout_detail", args=[1])
        self.assert_login_required("get", url)

    def test_workout_edit_requires_login(self):
        url = reverse("alors:workout_edit", args=[1])
        self.assert_login_required("get", url)

    def test_issue_list_requires_login(self):
        url = reverse("alors:issue_list")
        self.assert_login_required("get", url)

    def test_issue_add_requires_login(self):
        url = reverse("alors:issue_add")
        self.assert_login_required("get", url)

    def test_issue_edit_requires_login(self):
        url = reverse("alors:issue_edit", args=[1])
        self.assert_login_required("get", url)

    def test_issue_delete_requires_login(self):
        url = reverse("alors:issue_delete", args=[1])
        self.assert_login_required("post", url)

    def test_label_list_requires_login(self):
        url = reverse("alors:label_list")
        self.assert_login_required("get", url)

    def test_label_add_requires_login(self):
        url = reverse("alors:label_add")
        self.assert_login_required("get", url)

    def test_label_edit_requires_login(self):
        url = reverse("alors:label_edit", args=[1])
        self.assert_login_required("get", url)

    def test_label_delete_requires_login(self):
        url = reverse("alors:label_delete", args=[1])
        self.assert_login_required("post", url)

    def test_add_planned_comment_requires_login(self):
        url = reverse("alors:add_planned_comment", args=[1])
        self.assert_login_required("post", url)

    def test_add_workout_comment_requires_login(self):
        url = reverse("alors:add_workout_comment", args=[1])
        self.assert_login_required("post", url)
