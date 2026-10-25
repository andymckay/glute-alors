from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..models import UserProfile


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")

    def test_default_role_is_athlete(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(profile.role, UserProfile.Role.ATHLETE)
        self.assertEqual(profile.role, "athlete")

    def test_can_set_coach_role(self):
        profile = UserProfile.objects.create(
            user=self.user, role=UserProfile.Role.COACH
        )
        self.assertEqual(profile.role, "coach")
        self.assertEqual(profile.get_role_display(), "Coach")

    def test_visibility_holds_the_users_who_can_see_the_profile(self):
        other = User.objects.create_user(username="other", password="secret")
        profile = UserProfile.objects.create(user=self.user)

        profile.visibility.add(other)

        self.assertEqual(list(profile.visibility.all()), [other])

    def test_units_defaults_to_imperial(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(profile.units, UserProfile.WeightUnit.IMPERIAL)
        self.assertEqual(profile.get_units_display(), "Imperial (lb)")

    def test_can_choose_metric_units(self):
        profile = UserProfile.objects.create(
            user=self.user, units=UserProfile.WeightUnit.METRIC
        )
        self.assertEqual(profile.units, "metric")
        self.assertEqual(profile.get_units_display(), "Metric (kg)")

    def test_profile_is_one_to_one_with_user(self):
        UserProfile.objects.create(user=self.user)
        with self.assertRaises(Exception):
            UserProfile.objects.create(user=self.user)

    def test_related_name_links_back_to_user(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(self.user.profile, profile)

    def test_default_timezone_is_settings_time_zone(self):
        from django.conf import settings

        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(profile.timezone, settings.TIME_ZONE)

    def test_can_set_timezone(self):
        profile = UserProfile.objects.create(user=self.user, timezone="Europe/London")
        self.assertEqual(profile.timezone, "Europe/London")

    def test_show_add_plan_is_on_by_default(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertTrue(profile.show_add_plan)

    def test_daily_email_is_off_by_default(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertFalse(profile.send_daily_email)

    def test_can_turn_the_daily_email_on(self):
        profile = UserProfile.objects.create(user=self.user, send_daily_email=True)
        self.assertTrue(profile.send_daily_email)

    def test_comment_email_is_off_by_default(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertFalse(profile.send_comment_email)

    def test_can_turn_the_comment_email_on(self):
        profile = UserProfile.objects.create(user=self.user, send_comment_email=True)
        self.assertTrue(profile.send_comment_email)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="runner",
            password="secret123",
            email="runner@example.com",
        )
        self.client.force_login(self.user)

    def test_get_creates_profile_and_shows_email_and_timezone(self):
        response = self.client.get(reverse("alors:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email address")
        self.assertContains(response, "runner@example.com")
        self.assertNotContains(response, "Role")
        self.assertContains(response, "Timezone")
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_profile_page_lists_other_users_for_visibility(self):
        other = User.objects.create_user(username="other", password="secret")
        admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="secret"
        )

        response = self.client.get(reverse("alors:profile"))

        options = response.context["form"].fields["visibility"].queryset
        self.assertIn(other, options)
        self.assertNotIn(self.user, options)
        self.assertNotIn(admin, options)
        self.assertContains(response, 'name="visibility"')

    def test_post_updates_visibility(self):
        other = User.objects.create_user(username="other", password="secret")

        response = self.client.post(
            reverse("alors:profile"),
            {
                "units": "imperial",
                "timezone": "UTC",
                "email": "runner@example.com",
                "visibility": [other.pk],
            },
        )

        self.assertRedirects(response, reverse("alors:profile"))
        self.assertEqual(list(self.user.profile.visibility.all()), [other])

    def test_profile_page_shows_the_add_plan_option(self):
        response = self.client.get(reverse("alors:profile"))

        self.assertContains(response, "Show add plan")
        self.assertContains(response, 'name="show_add_plan"')

    def test_post_can_turn_the_add_plan_option_on_and_off(self):
        data = {
            "units": "imperial",
            "timezone": "UTC",
            "email": "runner@example.com",
            "show_add_plan": "on",
        }

        self.client.post(reverse("alors:profile"), data)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.show_add_plan)

        # An unticked box is simply absent from the post.
        data.pop("show_add_plan")
        self.client.post(reverse("alors:profile"), data)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.show_add_plan)

    def test_profile_page_shows_the_daily_email_unticked(self):
        response = self.client.get(reverse("alors:profile"))
        self.assertContains(response, "Send daily email")
        self.assertFalse(response.context["form"]["send_daily_email"].value())

    def test_profile_page_shows_the_comment_email_unticked(self):
        response = self.client.get(reverse("alors:profile"))
        self.assertContains(response, "Send email on comment")
        self.assertFalse(response.context["form"]["send_comment_email"].value())

    def test_post_can_turn_the_comment_email_on_and_off_again(self):
        data = {
            "units": "imperial",
            "timezone": "UTC",
            "email": "runner@example.com",
        }

        self.client.post(
            reverse("alors:profile"), {**data, "send_comment_email": "on"}
        )
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.send_comment_email)

        # An unticked box is simply absent from the post.
        self.client.post(reverse("alors:profile"), data)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.send_comment_email)

    def test_post_can_turn_the_daily_email_on_and_off_again(self):
        data = {
            "units": "imperial",
            "timezone": "UTC",
            "email": "runner@example.com",
        }

        self.client.post(reverse("alors:profile"), {**data, "send_daily_email": "on"})
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.send_daily_email)

        # An unticked box is simply absent from the post.
        self.client.post(reverse("alors:profile"), data)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.send_daily_email)

    def test_post_updates_timezone_and_email(self):
        response = self.client.post(
            reverse("alors:profile"),
            {
                "units": "imperial",
                "timezone": "Europe/London",
                "email": "coach@example.com",
            },
        )
        self.assertRedirects(response, reverse("alors:profile"))
        profile = self.user.profile
        self.assertEqual(profile.timezone, "Europe/London")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "coach@example.com")

    def test_profile_page_shows_units(self):
        response = self.client.get(reverse("alors:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Units")
        self.assertEqual(response.context["form"]["units"].value(), "imperial")

    def test_post_updates_units(self):
        response = self.client.post(
            reverse("alors:profile"),
            {
                "units": "metric",
                "timezone": "UTC",
                "email": "runner@example.com",
            },
        )
        self.assertRedirects(response, reverse("alors:profile"))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.units, "metric")

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            reverse("alors:profile"),
            {
                "units": "imperial",
                "timezone": "UTC",
                "email": "not-an-email",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "runner@example.com")

    def test_post_uploads_avatar_and_pages_show_it(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        avatar = SimpleUploadedFile(
            "avatar.png", b"fake-png-bytes", content_type="image/png"
        )
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("alors:profile"),
                    {
                        "units": "imperial",
                        "timezone": "America/New_York",
                        "email": "runner@example.com",
                        "avatar": avatar,
                    },
                )
                self.assertRedirects(response, reverse("alors:profile"))
                profile = self.user.profile
                self.assertTrue(profile.avatar.name.startswith("avatars/"))
                self.assertTrue(profile.avatar.url.startswith("/media/"))

                response = self.client.get(reverse("alors:profile"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, profile.avatar.url)

                # The avatar is shown in the navbar on other pages too.
                response = self.client.get(reverse("alors:calendar"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, profile.avatar.url)

    def test_profile_page_lists_all_pytz_timezones(self):
        import pytz

        response = self.client.get(reverse("alors:profile"))
        self.assertEqual(response.status_code, 200)
        for tz in ("Europe/London", "America/New_York", "Asia/Tokyo"):
            self.assertContains(response, f'value="{tz}"')
        self.assertGreater(
            len(pytz.all_timezones), 500
        )  # sanity: the field really is populated from pytz


class UserTimezoneMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tzuser", password="secret123")
        self.client.force_login(self.user)

    def test_activates_logged_in_users_timezone(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from django.utils import timezone

        from ..middleware import UserTimezoneMiddleware

        UserProfile.objects.create(user=self.user, timezone="Europe/London")

        captured = {}

        def get_response(request):
            captured["tz"] = timezone.get_current_timezone_name()
            return HttpResponse()

        request = RequestFactory().get("/")
        request.user = self.user
        UserTimezoneMiddleware(get_response)(request)
        self.assertEqual(captured["tz"], "Europe/London")

    def test_falls_back_to_default_timezone_without_profile(self):
        from django.conf import settings
        from django.http import HttpResponse
        from django.test import RequestFactory
        from django.utils import timezone

        from ..middleware import UserTimezoneMiddleware

        captured = {}

        def get_response(request):
            captured["tz"] = timezone.get_current_timezone_name()
            return HttpResponse()

        request = RequestFactory().get("/")
        request.user = self.user  # no profile yet
        UserTimezoneMiddleware(get_response)(request)
        self.assertEqual(captured["tz"], settings.TIME_ZONE)
