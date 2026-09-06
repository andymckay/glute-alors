from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import Label


class LabelModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.label = Label.objects.create(
            title="Build phase",
            colour=Label.Colour.SUCCESS,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            created_by=self.user,
        )

    def test_stores_fields(self):
        self.label.refresh_from_db()
        self.assertEqual(self.label.title, "Build phase")
        self.assertEqual(self.label.colour, "success")
        self.assertEqual(self.label.start_date, date(2026, 9, 1))
        self.assertEqual(self.label.end_date, date(2026, 9, 30))
        self.assertEqual(self.label.created_by, self.user)
        self.assertIsNotNone(self.label.created_at)
        self.assertIsNotNone(self.label.updated_at)

    def test_colour_choices_are_bootstrap_badge_colours(self):
        self.assertEqual(
            {choice[0] for choice in Label.Colour.choices},
            {
                "primary",
                "secondary",
                "success",
                "danger",
                "warning",
                "light",
                "dark",
            },
        )

    def test_colour_defaults_to_primary(self):
        label = Label.objects.create(
            title="No colour",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        self.assertEqual(label.colour, Label.Colour.PRIMARY)


class LabelViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.label = Label.objects.create(
            title="Build phase",
            colour=Label.Colour.SUCCESS,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            created_by=self.user,
        )

    def label_data(self, **overrides):
        data = {
            "title": "Recovery",
            "colour": Label.Colour.SUCCESS,
            "start_date": "2026-10-01",
            "end_date": "2026-10-14",
        }
        data.update(overrides)
        return data

    def test_list_shows_labels(self):
        response = self.client.get(reverse("alors:label_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build phase")
        self.assertContains(response, reverse("alors:label_add"))

    def test_add_sets_created_by_and_redirects(self):
        response = self.client.post(
            reverse("alors:label_add"),
            self.label_data(),
        )
        self.assertRedirects(response, reverse("alors:label_list"))
        label = Label.objects.get(title="Recovery")
        self.assertEqual(label.created_by, self.user)

    def test_add_rejects_end_before_start(self):
        response = self.client.post(
            reverse("alors:label_add"),
            self.label_data(
                start_date="2026-10-20",
                end_date="2026-10-01",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Label.objects.filter(title="Recovery").exists())

    def test_edit_page_renders_existing_data(self):
        response = self.client.get(reverse("alors:label_edit", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build phase")

    def test_edit_page_offers_delete(self):
        url = reverse("alors:label_delete", args=[self.label.pk])
        response = self.client.get(reverse("alors:label_edit", args=[self.label.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, url)
        self.assertContains(response, "Delete label")

    def test_delete_removes_label(self):
        response = self.client.post(reverse("alors:label_delete", args=[self.label.pk]))
        self.assertRedirects(response, reverse("alors:label_list"))
        self.assertFalse(Label.objects.filter(pk=self.label.pk).exists())

    def test_edit_updates_label(self):
        response = self.client.post(
            reverse("alors:label_edit", args=[self.label.pk]),
            self.label_data(title="Base phase", colour=Label.Colour.WARNING),
        )
        self.assertRedirects(response, reverse("alors:label_list"))
        self.label.refresh_from_db()
        self.assertEqual(self.label.title, "Base phase")
        self.assertEqual(self.label.colour, "warning")
