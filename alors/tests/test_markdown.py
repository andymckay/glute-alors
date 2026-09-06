from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ..models import PlannedWorkout, WarmUp, WorkoutType


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


class WorkoutDetailMarkdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runner", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="# Warm up heading\n\nSome **instructions**.",
            created_by=self.user,
        )
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            warm_up=self.warmup,
            notes="# Notes\n\nRuns with **pace**.",
        )

    def test_detail_renders_warmup_text_as_markdown(self):
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Warm up heading</h1>")
        self.assertContains(response, "<strong>instructions</strong>")

    def test_detail_renders_notes_as_markdown(self):
        response = self.client.get(
            reverse("alors:planned_detail", args=[self.workout.pk])
        )
        self.assertContains(response, "<h1>Notes</h1>")
        self.assertContains(response, "<strong>pace</strong>")
