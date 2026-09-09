from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import Issue


class IssueViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.issue = Issue.objects.create(title="App crashes")

    def test_list_shows_issues(self):
        response = self.client.get(reverse("alors:issue_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "App crashes")
        self.assertContains(response, reverse("alors:issue_add"))

    def test_add_creates_issue_and_redirects(self):
        response = self.client.post(
            reverse("alors:issue_add"),
            {"title": "New bug", "colour": "danger"},
        )
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.assertTrue(Issue.objects.filter(title="New bug").exists())

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:issue_edit", args=[self.issue.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "App crashes")

    def test_edit_updates_issue(self):
        url = reverse("alors:issue_edit", args=[self.issue.pk])
        response = self.client.post(
            url,
            {"title": "App crashes on login", "colour": "danger"},
        )
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.title, "App crashes on login")
        self.assertEqual(self.issue.colour, "danger")

    def test_delete_removes_issue(self):
        response = self.client.post(reverse("alors:issue_delete", args=[self.issue.pk]))
        self.assertRedirects(response, reverse("alors:issue_list"))
        self.assertFalse(Issue.objects.filter(pk=self.issue.pk).exists())

    def test_add_sets_created_by_to_logged_in_user(self):
        response = self.client.post(
            reverse("alors:issue_add"),
            {"title": "New bug", "colour": "success"},
        )
        self.assertEqual(response.status_code, 302)
        issue = Issue.objects.get(title="New bug")
        self.assertEqual(issue.created_by, self.user)

    def test_created_by_is_not_an_editable_field(self):
        from ..forms import IssueForm

        fields = IssueForm().fields
        self.assertNotIn("created_by", fields)
        self.assertIn("title", fields)
        self.assertIn("colour", fields)

    def test_issue_colour_defaults_to_primary(self):
        issue = Issue.objects.create(title="Bare")
        self.assertEqual(issue.colour, "primary")

    def test_timestamps_are_set_and_updated(self):
        self.issue.refresh_from_db()
        self.assertIsNotNone(self.issue.created_at)
        self.assertIsNotNone(self.issue.updated_at)
        created_before = self.issue.created_at
        updated_before = self.issue.updated_at

        self.issue.title = "Edited title."
        self.issue.save()
        self.issue.refresh_from_db()
        self.assertGreaterEqual(self.issue.updated_at, updated_before)
        self.assertEqual(self.issue.created_at, created_before)
