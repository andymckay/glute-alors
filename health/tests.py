from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Health
from .views import PAGE_SIZE


class HealthModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="runner", password="secret"
        )

    def test_records_measurements(self):
        health = Health.objects.create(
            created_by=self.user,
            weight="176.4",
            systolic=120,
            diastolic=80,
            resting_heart_rate=52,
        )

        health.refresh_from_db()
        self.assertEqual(health.created_by, self.user)
        self.assertEqual(health.weight, Decimal("176.4"))
        self.assertEqual(health.systolic, 120)
        self.assertEqual(health.diastolic, 80)
        self.assertEqual(health.resting_heart_rate, 52)
        self.assertIsNotNone(health.created_at)
        self.assertIsNotNone(health.updated_at)

    def test_blood_pressure_formats_as_systolic_over_diastolic(self):
        health = Health(systolic=118, diastolic=79)
        self.assertEqual(health.blood_pressure, "118/79")

    def test_blood_pressure_is_none_when_incomplete(self):
        self.assertIsNone(Health().blood_pressure)
        self.assertIsNone(Health(systolic=118).blood_pressure)
        self.assertIsNone(Health(diastolic=79).blood_pressure)

    def test_measurements_are_optional(self):
        health = Health.objects.create()

        health.refresh_from_db()
        self.assertIsNone(health.weight)
        self.assertIsNone(health.resting_heart_rate)

    def test_ordered_newest_first(self):
        older = Health.objects.create(created_by=self.user, weight="180.0")
        newer = Health.objects.create(created_by=self.user, weight="178.0")

        self.assertEqual(list(Health.objects.all()), [newer, older])


class HealthViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="runner", password="secret"
        )
        self.client.force_login(self.user)

    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("health:health_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("health:health_list"), response.url)

    def test_list_renders_entries(self):
        Health.objects.create(
            created_by=self.user,
            weight="176.4",
            systolic=120,
            diastolic=80,
            resting_heart_rate=52,
        )

        response = self.client.get(reverse("health:health_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "176.4 lb")
        self.assertContains(response, "120/80 mmHg")
        self.assertContains(response, "52 bpm")

    def test_add_page_renders_form(self):
        response = self.client.get(reverse("health:health_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a health entry")

    def test_add_creates_entry_for_current_user(self):
        response = self.client.post(
            reverse("health:health_add"),
            {
                "weight": "176.4",
                "systolic": "120",
                "diastolic": "80",
                "resting_heart_rate": "52",
            },
        )

        self.assertRedirects(response, reverse("health:health_list"))
        health = Health.objects.get()
        self.assertEqual(health.created_by, self.user)
        self.assertEqual(health.weight, Decimal("176.4"))
        self.assertEqual(health.blood_pressure, "120/80")
        self.assertEqual(health.resting_heart_rate, 52)

    def test_edit_page_prefills_entry(self):
        health = Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.get(reverse("health:health_edit", args=[health.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit health entry")

    def test_edit_updates_entry(self):
        health = Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.post(
            reverse("health:health_edit", args=[health.pk]),
            {
                "weight": "178.0",
                "systolic": "118",
                "diastolic": "79",
                "resting_heart_rate": "50",
            },
        )

        self.assertRedirects(response, reverse("health:health_list"))
        health.refresh_from_db()
        self.assertEqual(health.weight, Decimal("178.0"))
        self.assertEqual(health.blood_pressure, "118/79")
        self.assertEqual(health.resting_heart_rate, 50)

    def test_delete_removes_entry(self):
        health = Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.post(reverse("health:health_delete", args=[health.pk]))

        self.assertRedirects(response, reverse("health:health_list"))
        self.assertFalse(Health.objects.filter(pk=health.pk).exists())

    def test_delete_requires_post(self):
        health = Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.get(reverse("health:health_delete", args=[health.pk]))

        self.assertRedirects(response, reverse("health:health_list"))
        self.assertTrue(Health.objects.filter(pk=health.pk).exists())

    def test_list_paginates_entries(self):
        for i in range(PAGE_SIZE + 5):
            Health.objects.create(created_by=self.user, weight="180.0")

        first_page = self.client.get(reverse("health:health_list"))
        self.assertEqual(len(first_page.context["records"]), PAGE_SIZE)
        self.assertTrue(first_page.context["page_obj"].has_next())
        self.assertContains(first_page, "?page=2")

        second_page = self.client.get(reverse("health:health_list"), {"page": 2})
        self.assertEqual(len(second_page.context["records"]), 5)
        self.assertFalse(second_page.context["page_obj"].has_next())

    def test_list_falls_back_to_last_page_for_invalid_page(self):
        for i in range(PAGE_SIZE + 5):
            Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.get(reverse("health:health_list"), {"page": 999})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)

    def test_list_hides_pagination_for_single_page(self):
        Health.objects.create(created_by=self.user, weight="180.0")

        response = self.client.get(reverse("health:health_list"))

        self.assertNotContains(response, "?page=2")
