from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from datetime import datetime, timedelta

from ..models import Workout, WorkoutType


class MarkdownFilterTests(SimpleTestCase):
    def render(self, value):
        template = Template("{% load markdown_extras %}{{ value|markdown }}")
        return template.render(Context({"value": value}))

    def test_renders_headings(self):
        self.assertIn("<h1>Heading</h1>", self.render("# Heading"))

    def test_renders_emphasis(self):
        self.assertIn("<strong>bold</strong>", self.render("**bold**"))

    def test_empty_value_renders_nothing(self):
        self.assertEqual(self.render(""), "")

    def test_output_is_marked_safe(self):
        template = Template("{% load markdown_extras %}{{ value|markdown }}")
        output = template.render(Context({"value": "**bold**"}))
        self.assertNotIn("&lt;strong&gt;", output)

    def test_renders_bare_urls_as_links(self):
        output = self.render("See https://example.com/a for details")
        self.assertIn('<a href="https://example.com/a">', output)

    def test_renders_gfm_tables_and_task_lists(self):
        output = self.render("- [x] done")
        self.assertIn('type="checkbox"', output)


class WorkoutDetailMarkdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.workout = Workout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date=datetime(2026, 9, 5, 8, 30),
            total_time=timedelta(minutes=90),
            notes="# Notes\n\nRuns with **pace**.",
        )

    def test_detail_renders_notes_as_markdown(self):
        response = self.client.get(
            reverse("alors:workout_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Notes</h1>")
        self.assertContains(response, "<strong>pace</strong>")
