"""The 403, 404 and 500 pages Django serves once DEBUG is off.

Django's default handlers look for templates named ``403.html``, ``404.html``
and ``500.html``, render them with an empty context and set the status code
themselves, so what needs pinning is that the names are where Django looks and
that the site's own page comes back rather than the bare fallback.
"""

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, override_settings
from django.views.defaults import page_not_found, permission_denied, server_error


class ErrorPageTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/no-such-page/")
        # The 403 and 404 handlers hand the request to the template, so the
        # context processors run and need the user AuthenticationMiddleware
        # would normally have attached.
        self.request.user = AnonymousUser()

    def error_responses(self):
        return {
            403: permission_denied(self.request, PermissionDenied()),
            404: page_not_found(self.request, Exception("missing")),
            500: server_error(self.request),
        }

    def test_the_templates_are_where_django_looks_for_them(self):
        for name in ("403.html", "404.html", "500.html"):
            self.assertIsNotNone(get_template(name), name)

    def test_each_page_has_its_own_status_code_and_wording(self):
        wording = {
            403: "Not allowed",
            404: "Page not found",
            500: "Something broke",
        }
        for status, response in self.error_responses().items():
            with self.subTest(status=status):
                self.assertEqual(response.status_code, status)
                self.assertContains(response, wording[status], status_code=status)

    def test_every_page_keeps_the_site_chrome_and_a_way_back(self):
        for status, response in self.error_responses().items():
            with self.subTest(status=status):
                # The header and footer come from base.html.
                self.assertContains(response, "glute alors", status_code=status)
                self.assertContains(
                    response, "Back to the start", status_code=status
                )
                self.assertContains(response, 'href="/"', status_code=status)

    def test_the_pages_explain_themselves(self):
        wording = {
            403: "do not have permission",
            404: "could not find that page",
            500: "has been logged",
        }
        for status, response in self.error_responses().items():
            with self.subTest(status=status):
                self.assertContains(response, wording[status], status_code=status)

    @override_settings(DEBUG=False)
    def test_a_missing_url_serves_the_custom_page(self):
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "It may have been moved", status_code=404)
        # Not Django's technical 404 page, which DEBUG would otherwise show.
        self.assertNotContains(
            response, "Using the URLconf defined in", status_code=404
        )

    @override_settings(DEBUG=False)
    def test_the_404_keeps_the_logged_in_nav(self):
        """Django passes the request to the 404 handler, so the chrome is real."""
        user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(user)

        response = self.client.get("/no-such-page/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "runner", status_code=404)
