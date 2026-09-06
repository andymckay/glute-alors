from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import WarmUp


class WarmUpViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="Jog slowly for five minutes.",
            created_by=self.user,
        )

    def test_list_shows_warmups(self):
        response = self.client.get(reverse("alors:warmup_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Easy jog")
        self.assertContains(response, reverse("alors:warmup_add"))

    def test_add_sets_created_by_and_redirects(self):
        response = self.client.post(
            reverse("alors:warmup_add"),
            {"title": "Strides", "text": "Six short strides."},
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        warmup = WarmUp.objects.get(title="Strides")
        self.assertEqual(warmup.created_by, self.user)

    def test_edit_updates_warmup(self):
        url = reverse("alors:warmup_edit", args=[self.warmup.pk])
        response = self.client.post(
            url,
            {"title": "Easy jog & drills", "text": "Updated routine."},
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        self.warmup.refresh_from_db()
        self.assertEqual(self.warmup.title, "Easy jog & drills")
        self.assertEqual(self.warmup.text, "Updated routine.")

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:warmup_edit", args=[self.warmup.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.warmup.title)

    def test_delete_removes_warmup(self):
        response = self.client.post(
            reverse("alors:warmup_delete", args=[self.warmup.pk])
        )
        self.assertRedirects(response, reverse("alors:warmup_list"))
        self.assertFalse(WarmUp.objects.filter(pk=self.warmup.pk).exists())
