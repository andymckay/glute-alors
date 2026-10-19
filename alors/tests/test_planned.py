import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from ..models import (
    Label,
    PlannedWorkout,
    SavedWorkout,
    UserProfile,
    WeeklySummary,
    Workout,
    WorkoutType,
)
from weights.models import WeightsWorkout


class AddPlannedWorkoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)

    def add_workout(self):
        return self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "21.10",
            },
        )

    def test_add_sets_created_by_to_logged_in_user(self):
        response = self.add_workout()
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertEqual(workout.created_by, self.user)

    def test_saved_workout_picker_lists_every_saved_workout(self):
        SavedWorkout.objects.create(
            title="Tempo session",
            text="Warm up\n20 min tempo\nCool down",
            created_by=self.user,
        )
        response = self.client.get(reverse("alors:add_planned"), {"date": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_saved_workout"')
        self.assertContains(response, "Tempo session")
        # The option carries the text so the page can fill in the notes field.
        self.assertContains(
            response,
            'data-text="Warm up\n20 min tempo\nCool down"',
            html=False,
        )

    def test_saved_workout_picker_sits_above_notes_and_is_optional(self):
        from ..forms import PlannedWorkoutForm

        form = PlannedWorkoutForm()
        names = list(form.fields)
        self.assertEqual(names[names.index("saved_workout") + 1], "notes")
        self.assertFalse(form.fields["saved_workout"].required)

    def test_picking_a_saved_workout_still_saves_the_workout(self):
        saved_workout = SavedWorkout.objects.create(
            title="Tempo session", text="20 min tempo"
        )
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "21.10",
                "saved_workout": saved_workout.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlannedWorkout.objects.get().title, "Long run")

    def test_can_plan_two_workouts_on_the_same_day(self):
        self.add_workout()
        response = self.add_workout()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlannedWorkout.objects.count(), 2)

    def test_distance_field_is_optional_in_form(self):
        from ..forms import PlannedWorkoutForm

        self.assertFalse(PlannedWorkoutForm().fields["total_distance"].required)

    def test_distance_is_optional_when_adding(self):
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Recovery",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-06",
            },
        )
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertIsNone(workout.total_distance)

    def test_created_by_is_not_an_editable_form_field(self):
        from ..forms import PlannedWorkoutForm

        self.assertNotIn("created_by", PlannedWorkoutForm().fields)

    def test_user_related_name_links_back_to_workouts(self):
        self.add_workout()
        self.assertEqual(self.user.plannedworkout_set.count(), 1)
        self.assertEqual(
            self.user.plannedworkout_set.get().title,
            "Long run",
        )

    def test_add_page_shows_weekly_summary_for_provided_date(self):
        # Saving the workout creates a WeeklySummary for its week (09-06).
        self.add_workout()
        response = self.client.get(reverse("alors:add_planned"), {"date": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        # "<b>Last</b> week summary" / "<b>This</b> week summary" cards.
        self.assertContains(response, "week summary")
        self.assertContains(response, "Planned so far:")
        self.assertContains(response, "21.1")

    def test_add_page_shows_placeholder_when_week_has_no_summary(self):
        response = self.client.get(reverse("alors:add_planned"), {"date": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "week summary")
        self.assertContains(response, "No plan yet.")

    def test_add_page_without_a_date_renders_empty_summaries(self):
        response = self.client.get(reverse("alors:add_planned"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "week summary")
        self.assertContains(response, "No plan yet.")

    def test_weekly_summary_snippet_returns_summary_for_date(self):
        self.add_workout()
        response = self.client.get(
            reverse("alors:planned_weekly_summary"), {"date": "2026-09-05"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Run")
        self.assertContains(response, "21.1")

    def test_weekly_summary_snippet_returns_placeholder_without_data(self):
        response = self.client.get(
            reverse("alors:planned_weekly_summary"), {"date": "2026-09-05"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No plan yet.")


class MovePlannedWorkoutTests(TestCase):
    """The calendar JSON endpoint that moves and edits a planned workout."""

    def setUp(self):
        self.user = User.objects.create_user(username="mover", password="secret123")
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="10.00",
            created_by=self.user,
        )

    def move(self, date_value):
        return self.client.post(
            reverse("alors:move_planned_workout", args=[self.workout.pk]),
            {"date": date_value},
        )

    def test_move_changes_the_date(self):
        response = self.move("2026-09-08")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.workout.pk, "date": "2026-09-08"})
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.workout_date, date(2026, 9, 8))

    def test_move_refreshes_the_old_and_the_new_week_summaries(self):
        # 2026-09-05 belongs to the week ending Sunday 09-06; 09-15 to 09-20.
        self.move("2026-09-15")
        # Nothing is left in the old week, so its summary row is dropped.
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        new_week = WeeklySummary.objects.get(date=date(2026, 9, 20))
        self.assertEqual(new_week.summary["planned_workout"]["run"]["workouts"], 1)

    def test_move_rejects_an_invalid_date(self):
        response = self.move("not-a-date")
        self.assertEqual(response.status_code, 400)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.workout_date, date(2026, 9, 5))

    def test_move_rejects_an_empty_date(self):
        response = self.move("")
        self.assertEqual(response.status_code, 400)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.workout_date, date(2026, 9, 5))

    def test_move_allows_a_day_that_already_has_a_planned_workout(self):
        PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-10",
            total_distance="5.00",
        )
        response = self.move("2026-09-10")
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.workout_date, date(2026, 9, 10))
        self.assertEqual(
            PlannedWorkout.objects.filter(workout_date="2026-09-10").count(), 2
        )

    def test_move_rejects_a_get_request(self):
        url = reverse("alors:move_planned_workout", args=[self.workout.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def update(self, **fields):
        return self.client.post(
            reverse("alors:move_planned_workout", args=[self.workout.pk]),
            fields,
        )

    def test_update_changes_every_allowed_field(self):
        response = self.update(
            title="Tempo",
            workout_type=WorkoutType.RECOVERY,
            is_race="true",
            total_distance="5.25",
            notes="Take it easy",
            date="2026-09-12",
        )
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.title, "Tempo")
        self.assertEqual(self.workout.workout_type, WorkoutType.RECOVERY)
        self.assertTrue(self.workout.is_race)
        self.assertEqual(self.workout.total_distance, Decimal("5.25"))
        self.assertEqual(self.workout.notes, "Take it easy")
        self.assertEqual(self.workout.workout_date, date(2026, 9, 12))
        body = response.json()
        self.assertEqual(body["date"], "2026-09-12")
        self.assertEqual(body["title"], "Tempo")
        self.assertEqual(body["total_distance"], "5.25")
        self.assertIs(body["is_race"], True)

    def test_update_leaves_omitted_fields_alone(self):
        response = self.update(title="Tempo")
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.title, "Tempo")
        self.assertEqual(self.workout.workout_type, WorkoutType.RUN)
        self.assertEqual(self.workout.total_distance, Decimal("10.00"))
        self.assertEqual(self.workout.workout_date, date(2026, 9, 5))
        self.assertEqual(self.workout.notes, "")
        self.assertFalse(self.workout.is_race)

    def test_update_can_clear_the_distance_and_the_race_flag(self):
        self.workout.is_race = True
        self.workout.save()
        response = self.update(total_distance="", is_race="false")
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertIsNone(self.workout.total_distance)
        self.assertFalse(self.workout.is_race)

    def test_update_rejects_an_unknown_workout_type(self):
        response = self.update(workout_type="juggling")
        self.assertEqual(response.status_code, 400)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.workout_type, WorkoutType.RUN)

    def test_update_rejects_an_invalid_distance(self):
        response = self.update(total_distance="far")
        self.assertEqual(response.status_code, 400)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.total_distance, Decimal("10.00"))

    def test_update_requires_at_least_one_allowed_field(self):
        response = self.update(nope="value")
        self.assertEqual(response.status_code, 400)

    def test_update_accepts_a_json_body(self):
        response = self.client.post(
            reverse("alors:move_planned_workout", args=[self.workout.pk]),
            data=json.dumps({"title": "Tempo", "total_distance": 8.5}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.title, "Tempo")
        self.assertEqual(self.workout.total_distance, Decimal("8.50"))


class DuplicatePlannedWorkoutTests(TestCase):
    """Copying a planned workout onto the same day from the calendar."""

    def setUp(self):
        self.user = User.objects.create_user(username="copier", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            is_race=True,
            notes="Easy pace.",
            status="done",
            comment_count=3,
            created_by=self.user,
        )

    def duplicate(self):
        return self.client.post(
            reverse("alors:duplicate_planned", args=[self.workout.pk])
        )

    def test_duplicate_creates_a_copy_on_the_same_day(self):
        response = self.duplicate()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlannedWorkout.objects.count(), 2)
        copy = PlannedWorkout.objects.exclude(pk=self.workout.pk).get()
        self.assertEqual(copy.workout_date, date(2026, 9, 5))
        self.assertEqual(copy.title, "Long run")
        self.assertEqual(copy.workout_type, WorkoutType.RUN)
        self.assertEqual(copy.total_distance, Decimal("21.10"))
        self.assertTrue(copy.is_race)
        self.assertEqual(copy.notes, "Easy pace.")
        self.assertEqual(copy.created_by, self.user)

    def test_duplicate_does_not_copy_status_or_comments(self):
        self.duplicate()
        copy = PlannedWorkout.objects.exclude(pk=self.workout.pk).get()
        self.assertEqual(copy.status, "")
        self.assertEqual(copy.comment_count, 0)

    def test_duplicate_leaves_the_original_untouched(self):
        self.duplicate()
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.status, "done")
        self.assertEqual(self.workout.comment_count, 3)

    def test_duplicate_refreshes_the_weekly_summary(self):
        self.duplicate()
        summary = WeeklySummary.objects.get(date=date(2026, 9, 6))
        self.assertEqual(summary.summary["planned_workout"]["run"]["workouts"], 2)

    def test_duplicate_rejects_a_get_request(self):
        url = reverse("alors:duplicate_planned", args=[self.workout.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_calendar_card_posts_to_the_duplicate_endpoint(self):
        response = self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("alors:duplicate_planned", args=[self.workout.pk])}"',
        )
        self.assertContains(response, "Duplicate")


class PlannedEditModalTests(TestCase):
    """The Bootstrap modal used to edit a planned workout from the calendar."""

    def setUp(self):
        self.user = User.objects.create_user(username="editor", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            notes="Easy pace.",
            created_by=self.user,
        )

    def calendar(self):
        return self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})

    def test_calendar_renders_a_modal_per_planned_workout(self):
        response = self.calendar()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="edit-planned-{self.workout.pk}"')
        self.assertContains(
            response,
            f'data-bs-target="#edit-planned-{self.workout.pk}"',
        )
        self.assertContains(
            response,
            f'action="{reverse("alors:edit_planned", args=[self.workout.pk])}"',
        )

    def test_modal_form_has_every_field_prefilled(self):
        content = self.calendar().content.decode()
        for name in [
            "title",
            "workout_type",
            "is_race",
            "workout_date",
            "total_distance",
            "notes",
        ]:
            self.assertIn(f'name="{name}"', content)
        # Ids are namespaced per workout so the modals do not clash.
        self.assertIn(f'id="edit-{self.workout.pk}-title"', content)
        self.assertIn('value="Long run"', content)
        self.assertIn('value="2026-09-05"', content)
        self.assertIn('value="21.10"', content)
        self.assertIn("Easy pace.", content)

    def test_modal_offers_saved_workouts_to_copy_into_notes(self):
        SavedWorkout.objects.create(
            title="Tempo session",
            text="Warm up\n20 min tempo\nCool down",
            created_by=self.user,
        )
        content = self.calendar().content.decode()
        self.assertIn('name="saved_workout"', content)
        self.assertIn("Tempo session", content)
        # The option carries the text for the client-side notes autofill.
        self.assertIn('data-text="Warm up\n20 min tempo\nCool down"', content)
        self.assertIn('name="notes"', content)

    def test_every_modal_gets_the_shared_saved_workout_picker(self):
        SavedWorkout.objects.create(
            title="Tempo session", text="20 min tempo", created_by=self.user
        )
        PlannedWorkout.objects.create(
            title="Easy jog",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-06",
            total_distance="5.00",
            created_by=self.user,
        )
        content = self.calendar().content.decode()
        # Two edit modals plus the shared add modal.
        self.assertEqual(content.count('name="saved_workout"'), 3)
        self.assertEqual(content.count('data-text="20 min tempo"'), 3)

    def test_calendar_queries_do_not_scale_with_planned_workouts(self):
        SavedWorkout.objects.create(
            title="Tempo session", text="20 min tempo", created_by=self.user
        )
        for i in range(5):
            PlannedWorkout.objects.create(
                title=f"Run {i}",
                workout_type=WorkoutType.RUN,
                workout_date=f"2026-09-{10 + i:02d}",
                total_distance="10.00",
                created_by=self.user,
            )
        with CaptureQueriesContext(connection) as ctx:
            self.calendar()
        planned = [
            q for q in ctx.captured_queries if "alors_plannedworkout" in q["sql"]
        ]
        saved = [q for q in ctx.captured_queries if "alors_savedworkout" in q["sql"]]
        # One query each, however many modals the page renders.
        self.assertEqual(len(planned), 1)
        self.assertEqual(len(saved), 1)

    def test_modal_post_updates_the_workout(self):
        response = self.client.post(
            reverse("alors:edit_planned", args=[self.workout.pk]),
            {
                "title": "Tempo",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "5.00",
                "notes": "Faster.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.workout.refresh_from_db()
        self.assertEqual(self.workout.title, "Tempo")
        self.assertEqual(self.workout.total_distance, Decimal("5.00"))
        self.assertEqual(self.workout.notes, "Faster.")


class CalendarDragHandleTests(TestCase):
    """The drag handle, not the whole card, starts a calendar drag."""

    def setUp(self):
        self.user = User.objects.create_user(username="dragger", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="10.00",
            created_by=self.user,
        )

    def test_card_uses_a_drag_handle_and_is_not_draggable(self):
        response = self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('class="js-drag-handle', content)
        self.assertIn('draggable="true"', content)
        self.assertIn(f'data-planned-id="{self.workout.pk}"', content)
        # The wrapper is no longer the drag source.
        self.assertNotIn('js-planned-card" draggable', content)

    def test_monthly_drop_target_is_the_table_cell(self):
        response = self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})
        content = response.content.decode()
        self.assertIn('<td class="js-planned-drop"', content)
        self.assertIn('data-date="2026-09-05"', content)
        # The old inner drop wrapper is gone.
        self.assertNotIn('<div class="js-planned-drop"', content)


class CalendarWorkoutQueryTests(TestCase):
    """Rendering workout cards must not look up the planned workout each time."""

    def setUp(self):
        self.user = User.objects.create_user(username="cal", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_planned_lookup_is_not_query_per_workout_card(self):
        for i in range(4):
            PlannedWorkout.objects.create(
                workout_type=WorkoutType.RUN,
                workout_date=f"2026-09-{5 + i:02d}",
                total_distance="10.00",
                created_by=self.user,
            )
            Workout.objects.create(
                workout_date=datetime(2026, 9, 5 + i, 8, 0),
                total_time=timedelta(minutes=45),
                workout_type=WorkoutType.RUN,
                created_by=self.user,
            )
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        planned = [
            q for q in ctx.captured_queries if "alors_plannedworkout" in q["sql"]
        ]
        self.assertEqual(len(planned), 1)

    def test_calendar_does_not_fetch_workout_data(self):
        Workout.objects.create(
            workout_date=datetime(2026, 9, 5, 8),
            total_time=timedelta(minutes=45),
            workout_type=WorkoutType.RUN,
            workout_data='{"record_mesgs": []}',
            created_by=self.user,
        )
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})
        self.assertFalse(any("workout_data" in q["sql"] for q in ctx.captured_queries))


class AddPlannedModalTests(TestCase):
    """The shared "Add plan" modal on the monthly and weekly calendar."""

    def setUp(self):
        self.user = User.objects.create_user(username="planner", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_monthly_renders_the_add_modal_and_wires_the_links(self):
        content = self.client.get(
            reverse("alors:calendar"), {"d": "2026-11-05"}
        ).content.decode()
        self.assertIn('id="add-planned"', content)
        self.assertIn(f'action="{reverse("alors:add_planned")}"', content)
        # The link opens the modal and carries the day it was clicked on.
        self.assertIn('data-bs-target="#add-planned" data-date="2026-11-05"', content)

    def test_weekly_renders_the_add_modal(self):
        content = self.client.get(
            reverse("alors:calendar"), {"d": "2026-11-05", "r": "w"}
        ).content.decode()
        self.assertIn('id="add-planned"', content)
        self.assertIn('data-bs-target="#add-planned" data-date="2026-11-05"', content)

    def test_add_modal_form_creates_a_planned_workout(self):
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-11-05",
                "total_distance": "21.10",
            },
        )
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertEqual(workout.workout_date, date(2026, 11, 5))
        self.assertEqual(workout.created_by, self.user)


class BusyModalTests(TestCase):
    """Deleting, editing and duplicating show a busy modal while loading."""

    def setUp(self):
        self.user = User.objects.create_user(username="busy", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            created_by=self.user,
        )

    def calendar(self):
        return self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})

    def test_the_thinking_modal_is_on_the_page(self):
        self.assertContains(self.calendar(), 'id="thinking"')

    def test_calendar_action_forms_show_the_busy_modal(self):
        content = self.calendar().content.decode()
        self.assertIn(
            f'action="{reverse("alors:duplicate_planned", args=[self.workout.pk])}"'
            ' class="d-inline js-busy-form"',
            content,
        )
        self.assertIn(
            f'action="{reverse("alors:delete_planned", args=[self.workout.pk])}"'
            ' class="d-inline js-busy-form"',
            content,
        )
        self.assertIn('data-confirm="Delete this planned workout?"', content)
        self.assertIn(
            f'action="{reverse("alors:edit_planned", args=[self.workout.pk])}"'
            ' class="js-busy-form"',
            content,
        )

    def test_add_modal_form_shows_the_busy_modal(self):
        content = self.calendar().content.decode()
        self.assertIn(
            f'action="{reverse("alors:add_planned")}" class="js-busy-form"',
            content,
        )

    def test_edit_page_delete_form_shows_the_busy_modal(self):
        content = self.client.get(
            reverse("alors:edit_planned", args=[self.workout.pk])
        ).content.decode()
        self.assertIn(
            f'action="{reverse("alors:delete_planned", args=[self.workout.pk])}"'
            ' class="js-busy-form"',
            content,
        )
        self.assertIn(
            'data-confirm="Are you sure you want to delete this planned workout?"',
            content,
        )


class DeletePlannedWorkoutTests(TestCase):
    """Deleting a planned workout from the calendar's confirm prompt."""

    def setUp(self):
        self.user = User.objects.create_user(username="deleter", password="x")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.workout = PlannedWorkout.objects.create(
            title="Long run",
            workout_type=WorkoutType.RUN,
            workout_date="2026-09-05",
            total_distance="21.10",
            created_by=self.user,
        )

    def delete(self):
        return self.client.post(reverse("alors:delete_planned", args=[self.workout.pk]))

    def test_calendar_delete_link_prompts_for_confirmation(self):
        content = self.client.get(
            reverse("alors:calendar"), {"d": "2026-09-05"}
        ).content.decode()
        self.assertIn(
            f'action="{reverse("alors:delete_planned", args=[self.workout.pk])}"',
            content,
        )
        self.assertIn('data-confirm="Delete this planned workout?"', content)

    def test_delete_removes_the_workout(self):
        response = self.delete()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PlannedWorkout.objects.filter(pk=self.workout.pk).exists())
        self.assertEqual(response.url, "/calendar/?d=2026-09-05#date-2026-09-05")

    def test_delete_rejects_a_get_request(self):
        url = reverse("alors:delete_planned", args=[self.workout.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(PlannedWorkout.objects.filter(pk=self.workout.pk).exists())


class CalendarRangeTests(TestCase):
    """Phones default to the weekly view when no range cookie exists."""

    IPHONE = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
    )
    ANDROID_PHONE = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
    )
    IPAD = (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
    )
    DESKTOP = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 Safari/605.1.15"
    )

    def setUp(self):
        self.user = User.objects.create_user(username="phone", password="secret")
        UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def get(self, **extra):
        return self.client.get(
            reverse("alors:calendar"), {"d": "2026-09-05"}, **extra
        )

    def test_desktop_without_a_range_cookie_gets_monthly(self):
        response = self.get(HTTP_USER_AGENT=self.DESKTOP)
        self.assertEqual(response.context["template"], "monthly")

    def test_phone_without_a_range_cookie_gets_weekly(self):
        response = self.get(HTTP_USER_AGENT=self.IPHONE)
        self.assertEqual(response.context["template"], "weekly")

    def test_android_phone_without_a_range_cookie_gets_weekly(self):
        response = self.get(HTTP_USER_AGENT=self.ANDROID_PHONE)
        self.assertEqual(response.context["template"], "weekly")

    def test_tablet_without_a_range_cookie_gets_monthly(self):
        response = self.get(HTTP_USER_AGENT=self.IPAD)
        self.assertEqual(response.context["template"], "monthly")

    def test_cookie_wins_over_the_phone_user_agent(self):
        self.client.cookies["r"] = "m"
        response = self.get(HTTP_USER_AGENT=self.IPHONE)
        self.assertEqual(response.context["template"], "monthly")

    def test_explicit_range_wins_over_the_phone_user_agent(self):
        response = self.client.get(
            reverse("alors:calendar"),
            {"d": "2026-09-05", "r": "m"},
            HTTP_USER_AGENT=self.IPHONE,
        )
        self.assertEqual(response.context["template"], "monthly")


class CalendarAddPlanOptionTests(TestCase):
    """The profile's show-add-plan option controls the calendar's add UI."""

    FUTURE = "2099-01-15"

    def setUp(self):
        self.user = User.objects.create_user(username="planner", password="secret")
        self.client.force_login(self.user)

    def get(self, **params):
        return self.client.get(
            reverse("alors:calendar"), {"d": self.FUTURE, **params}
        )

    def test_add_plan_is_shown_by_default(self):
        UserProfile.objects.create(user=self.user)

        response = self.get()

        self.assertContains(response, 'id="add-planned"')
        self.assertContains(response, ">Add plan<")

    def test_add_plan_is_shown_without_a_profile(self):
        response = self.get()

        self.assertContains(response, 'id="add-planned"')
        self.assertContains(response, ">Add plan<")

    def test_monthly_add_plan_is_hidden_when_turned_off(self):
        UserProfile.objects.create(user=self.user, show_add_plan=False)

        response = self.get()

        self.assertNotContains(response, 'id="add-planned"')
        self.assertNotContains(response, ">Add plan<")

    def test_weekly_add_plan_is_hidden_when_turned_off(self):
        UserProfile.objects.create(user=self.user, show_add_plan=False)

        response = self.get(r="w")

        self.assertNotContains(response, 'id="add-planned"')
        self.assertNotContains(response, ">Add plan<")


class CalendarVisibilityTests(TestCase):
    """Calendar and weekly views show only the user's own and shared records."""

    def setUp(self):
        self.viewer = User.objects.create_user(username="viewer", password="secret")
        self.owner = User.objects.create_user(username="owner", password="secret")
        self.stranger = User.objects.create_user(
            username="stranger", password="secret"
        )
        UserProfile.objects.create(user=self.viewer)
        owner_profile = UserProfile.objects.create(user=self.owner)
        UserProfile.objects.create(user=self.stranger)
        # The owner lets the viewer see their calendar; the stranger shares
        # with nobody.
        owner_profile.visibility.add(self.viewer)
        self.client.force_login(self.viewer)

    def _records(self, user, name):
        day = date(2026, 9, 5)
        PlannedWorkout.objects.create(
            created_by=user,
            workout_type=WorkoutType.RUN,
            workout_date=day,
            total_distance="10.00",
        )
        Workout.objects.create(
            created_by=user,
            workout_type=WorkoutType.RUN,
            workout_date=datetime(2026, 9, 5, 8),
            total_time=timedelta(minutes=45),
        )
        WeightsWorkout.objects.create(
            created_by=user,
            is_actual=True,
            title=f"{name}-weights",
            started_at=datetime(2026, 9, 5, 9),
        )
        Label.objects.create(
            created_by=user,
            title=f"{name}-label",
            start_date=day,
            end_date=day,
        )
        SavedWorkout.objects.create(
            created_by=user,
            title=f"{name}-saved",
            text="Session",
        )

    def _assert_shared_records_only(self, response):
        content = response.content.decode().lower()
        for name in ("viewer", "owner"):
            self.assertIn(f"{name}-weights", content)
            self.assertIn(f"{name}-label", content)
            self.assertIn(f"{name}-saved", content)
        for name in ("stranger",):
            self.assertNotIn(name, content)
            self.assertNotIn(f"{name}-weights", content)
            self.assertNotIn(f"{name}-label", content)
            self.assertNotIn(f"{name}-saved", content)

    def test_monthly_calendar_shows_own_and_shared_records_only(self):
        for user, name in (
            (self.viewer, "viewer"),
            (self.owner, "owner"),
            (self.stranger, "stranger"),
        ):
            self._records(user, name)

        response = self.client.get(reverse("alors:calendar"), {"d": "2026-09-05"})

        self._assert_shared_records_only(response)

    def test_weekly_calendar_shows_own_and_shared_records_only(self):
        for user, name in (
            (self.viewer, "viewer"),
            (self.owner, "owner"),
            (self.stranger, "stranger"),
        ):
            self._records(user, name)

        response = self.client.get(
            reverse("alors:calendar"), {"d": "2026-09-05", "r": "w"}
        )

        self._assert_shared_records_only(response)


class WeeklySummaryModelTests(TestCase):
    def test_can_store_nested_json_summary(self):
        data = {
            "total_distance_km": 42.5,
            "workouts": 5,
            "issues": ["Sore knee"],
        }
        summary = WeeklySummary.objects.create(
            date=date(2026, 9, 7),
            summary=data,
        )
        summary.refresh_from_db()
        self.assertEqual(summary.date, date(2026, 9, 7))
        self.assertEqual(summary.summary, data)

    def test_summary_defaults_to_empty_dict(self):
        summary = WeeklySummary.objects.create(date=date(2026, 9, 7))
        self.assertEqual(summary.summary, {})

    def test_can_store_a_list(self):
        summary = WeeklySummary.objects.create(
            date=date(2026, 9, 7),
            summary=["ran", "swam"],
        )
        summary.refresh_from_db()
        self.assertEqual(summary.summary, ["ran", "swam"])


class WeeklySummarySignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="summariser", password="secret")

    def create_planned(self, workout_date, distance="10.00", workout_type="run"):
        return PlannedWorkout.objects.create(
            workout_type=workout_type,
            workout_date=workout_date,
            total_distance=distance,
            created_by=self.user,
        )

    def create_workout_record(self, workout_date, distance="10.00", workout_type="run"):
        if isinstance(workout_date, date) and not isinstance(workout_date, datetime):
            workout_date = datetime.combine(workout_date, datetime.min.time())
        return Workout.objects.create(
            workout_date=workout_date,
            total_time=timedelta(minutes=30),
            workout_type=workout_type,
            total_distance=distance,
            created_by=self.user,
        )

    def summary_for(self, sunday):
        return WeeklySummary.objects.get(date=sunday, created_by=self.user)

    def test_planned_workout_summarised_by_type(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # Wednesday
        summary = self.summary_for(date(2026, 9, 6))  # that week's Sunday
        self.assertEqual(
            summary.summary,
            {
                "planned_workout": {
                    "run": {
                        "workouts": 1,
                        "total_distance": 10.0,
                        "total_time": 0,
                    }
                },
                "workout": {},
                "effort_feeling": [],
            },
        )

    def test_summary_lists_the_effort_and_feeling_of_each_workout(self):
        # The list is flat (not grouped by type) and ordered by date.
        Workout.objects.create(
            workout_date=datetime(2026, 9, 8, 8, 0),
            total_time=timedelta(minutes=30),
            workout_type="run",
            total_distance="10.00",
            effort=6,
            feeling=4,
            created_by=self.user,
        )
        Workout.objects.create(
            workout_date=datetime(2026, 9, 7, 8, 0),
            total_time=timedelta(minutes=20),
            workout_type="walk",
            total_distance="2.00",
            effort=2,
            created_by=self.user,
        )
        summary = self.summary_for(date(2026, 9, 13))
        self.assertEqual(
            summary.summary["effort_feeling"],
            [
                {"workout_type": "walk", "effort": 2, "feeling": None},
                {"workout_type": "run", "effort": 6, "feeling": 4},
            ],
        )

    def test_planned_types_are_grouped(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # Wed
        self.create_planned(date(2026, 9, 4), distance="3.00", workout_type="walk")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["planned_workout"],
            {
                "run": {
                    "workouts": 1,
                    "total_distance": 10.0,
                    "total_time": 0,
                },
                "walk": {
                    "workouts": 1,
                    "total_distance": 3.0,
                    "total_time": 0,
                },
            },
        )

    def test_workout_summarised_by_type_with_time(self):
        self.create_workout_record(date(2026, 9, 2), distance="10.00")
        self.create_workout_record(date(2026, 9, 4), distance="5.00")
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["workout"],
            {
                "run": {
                    "workouts": 2,
                    "total_distance": 15.0,
                    "total_time": 3600,  # 2 x 30 minutes
                }
            },
        )

    def test_planned_and_workout_kept_separate(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")  # planned run
        self.create_workout_record(
            date(2026, 9, 4), distance="5.00", workout_type="run"
        )
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(
            summary.summary["planned_workout"]["run"]["total_distance"], 10.0
        )
        self.assertEqual(summary.summary["workout"]["run"]["total_distance"], 5.0)
        self.assertEqual(summary.summary["workout"]["run"]["total_time"], 1800)

    def test_updating_workout_record_refreshes_summary(self):
        record = self.create_workout_record(date(2026, 9, 2), distance="10.00")
        record.total_distance = "15.00"
        record.save()
        summary = self.summary_for(date(2026, 9, 6))
        self.assertEqual(summary.summary["workout"]["run"]["total_distance"], 15.0)

    def test_moving_workout_record_updates_both_weeks(self):
        record = self.create_workout_record(date(2026, 9, 2))  # week ending 09-06
        record.workout_date = datetime(2026, 9, 10, 8, 0)  # week ending 09-13
        record.save()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        summary = self.summary_for(date(2026, 9, 13))
        self.assertEqual(summary.summary["workout"]["run"]["workouts"], 1)

    def test_deleting_workout_record_removes_weekly_summary(self):
        record = self.create_workout_record(date(2026, 9, 2))
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        record.delete()
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())

    def test_each_owner_gets_their_own_summary(self):
        other = User.objects.create_user(username="other", password="secret")
        self.create_planned(date(2026, 9, 2), distance="10.00")
        PlannedWorkout.objects.create(
            created_by=other,
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 3),
            total_distance="5.00",
        )

        mine = WeeklySummary.objects.get(date=date(2026, 9, 6), created_by=self.user)
        theirs = WeeklySummary.objects.get(date=date(2026, 9, 6), created_by=other)

        self.assertEqual(
            mine.summary["planned_workout"]["run"]["total_distance"], 10.0
        )
        self.assertEqual(
            theirs.summary["planned_workout"]["run"]["total_distance"], 5.0
        )

    def test_model_helpers_sum_the_new_structure(self):
        self.create_planned(date(2026, 9, 2), distance="10.00")
        self.create_planned(date(2026, 9, 4), distance="3.00", workout_type="walk")
        self.create_workout_record(date(2026, 9, 2), distance="5.00")
        summary = self.summary_for(date(2026, 9, 6)).summary
        self.assertEqual(summary["planned_workout"]["run"]["workouts"], 1)
        self.assertEqual(summary["planned_workout"]["walk"]["workouts"], 1)
        self.assertEqual(summary["planned_workout"]["run"]["total_distance"], 10.0)
        self.assertEqual(summary["workout"]["run"]["workouts"], 1)
        self.assertEqual(summary["workout"]["run"]["total_distance"], 5.0)


class RecreateWeeklySummariesCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rebuilder", password="secret")

    def create_planned(self, workout_date, distance="10.00", workout_type="run"):
        return PlannedWorkout.objects.create(
            workout_type=workout_type,
            workout_date=workout_date,
            total_distance=distance,
            created_by=self.user,
        )

    def test_recreates_a_deleted_summary(self):
        self.create_planned(date(2026, 9, 2))
        WeeklySummary.objects.filter(date=date(2026, 9, 6)).delete()

        call_command("recreate_weekly_summaries")

        summary = WeeklySummary.objects.get(
            date=date(2026, 9, 6), created_by=self.user
        )
        self.assertEqual(summary.summary["planned_workout"]["run"]["workouts"], 1)

    def test_recreates_a_summary_for_each_owner(self):
        other = User.objects.create_user(username="other", password="secret")
        self.create_planned(date(2026, 9, 2))
        PlannedWorkout.objects.create(
            created_by=other,
            workout_type=WorkoutType.RUN,
            workout_date=date(2026, 9, 3),
            total_distance="5.00",
        )

        call_command("recreate_weekly_summaries")

        self.assertEqual(
            WeeklySummary.objects.filter(date=date(2026, 9, 6)).count(), 2
        )

    def test_overwrites_stale_summary_data(self):
        self.create_planned(date(2026, 9, 2))
        WeeklySummary.objects.filter(date=date(2026, 9, 6)).update(
            summary={"planned_workout": {"run": {"workouts": 99}}}
        )

        call_command("recreate_weekly_summaries")

        summary = WeeklySummary.objects.get(
            date=date(2026, 9, 6), created_by=self.user
        )
        self.assertEqual(summary.summary["planned_workout"]["run"]["workouts"], 1)

    def test_drops_summaries_for_weeks_with_no_workouts(self):
        self.create_planned(date(2026, 9, 2))  # week ending 09-06
        self.create_planned(date(2026, 9, 16))  # week ending 09-20
        # An orphan summary in an empty week inside the rebuilt range.
        WeeklySummary.objects.create(date=date(2026, 9, 13), summary={"junk": True})

        call_command("recreate_weekly_summaries")

        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 13)).exists())
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        self.assertTrue(WeeklySummary.objects.filter(date=date(2026, 9, 20)).exists())

    def test_start_and_end_limit_the_rebuilt_range(self):
        self.create_planned(date(2026, 9, 2))  # week ending 09-06
        self.create_planned(date(2026, 9, 16))  # week ending 09-20
        WeeklySummary.objects.filter(date=date(2026, 9, 6)).update(
            summary={"stale": True}
        )

        call_command(
            "recreate_weekly_summaries", "--start", "2026-09-16", "--end", "2026-09-16"
        )

        # The 09-06 week is outside the range and keeps its stale data.
        untouched = WeeklySummary.objects.get(date=date(2026, 9, 6))
        self.assertEqual(untouched.summary, {"stale": True})
        rebuilt = WeeklySummary.objects.get(date=date(2026, 9, 20), created_by=self.user)
        self.assertEqual(rebuilt.summary["planned_workout"]["run"]["workouts"], 1)

    def test_no_data_is_a_no_op(self):
        call_command("recreate_weekly_summaries")
        self.assertEqual(WeeklySummary.objects.count(), 0)

    def test_invalid_start_date_raises_command_error(self):
        self.create_planned(date(2026, 9, 2))
        with self.assertRaises(CommandError):
            call_command("recreate_weekly_summaries", "--start", "not-a-date")


class PlannedStatusUpdateTests(TestCase):
    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date(2026, 9, 5),
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def create_workout(self, **overrides):
        values = {
            "workout_date": datetime(2026, 9, 5, 8, 0),
            "total_time": timedelta(minutes=50),
            "workout_type": WorkoutType.RUN,
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return Workout.objects.create(**values)

    def test_within_20_percent_marks_done(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("10.50"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "done")

    def test_under_20_percent_marks_under(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("7.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "under")

    def test_over_20_percent_marks_over(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("13.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "over")

    def test_sums_all_workouts_of_same_type_and_day(self):
        planned = self.create_planned()
        self.create_workout(total_distance=Decimal("5.00"))
        self.create_workout(total_distance=Decimal("5.50"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "done")

    def test_different_type_is_not_matched(self):
        planned = self.create_planned()
        self.create_workout(
            workout_type=WorkoutType.WALK,
            total_distance=Decimal("2.00"),
        )
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_different_day_is_not_matched(self):
        planned = self.create_planned()
        self.create_workout(workout_date=datetime(2026, 9, 6, 8, 0))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_planned_without_distance_is_untouched(self):
        planned = self.create_planned(total_distance=None)
        self.create_workout(total_distance=Decimal("10.00"))
        planned.refresh_from_db()
        self.assertEqual(planned.status, "")

    def test_multiple_plans_for_type_and_day_are_not_matched(self):
        # Two plans on the same day are allowed, but the status is only set
        # when there is a single unambiguous plan for that type and day.
        self.create_planned()
        self.create_planned(title="Second run")
        self.create_workout(total_distance=Decimal("10.00"))
        self.assertEqual(PlannedWorkout.objects.filter(status="done").count(), 0)


class MarkMissCommandTests(TestCase):
    def create_planned(self, **overrides):
        values = {
            "workout_type": WorkoutType.RUN,
            "workout_date": date.today(),
            "total_distance": Decimal("10.00"),
        }
        values.update(overrides)
        return PlannedWorkout.objects.create(**values)

    def test_marks_past_workouts_without_status_as_missed(self):
        past = self.create_planned(workout_date=date.today() - timedelta(days=3))
        call_command("mark_miss")
        past.refresh_from_db()
        self.assertEqual(past.status, "missed")

    def test_does_not_change_past_workouts_with_a_status(self):
        done = self.create_planned(
            workout_date=date.today() - timedelta(days=3),
            status="done",
        )
        call_command("mark_miss")
        done.refresh_from_db()
        self.assertEqual(done.status, "done")

    def test_does_not_mark_today_or_future_workouts(self):
        today = self.create_planned(workout_date=date.today())
        future = self.create_planned(workout_date=date.today() + timedelta(days=2))
        call_command("mark_miss")
        today.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(today.status, "")
        self.assertEqual(future.status, "")


class WeeklySummaryTimezoneTests(TestCase):
    """Weekly summaries must bucket workouts by their local date."""

    def setUp(self):
        self.owner = User.objects.create_user(username="runner", password="secret")
        UserProfile.objects.create(user=self.owner, timezone="America/New_York")

    def create_workout(self, workout_date, **overrides):
        values = {
            "total_time": timedelta(minutes=30),
            "workout_type": "run",
            "total_distance": "10.00",
            "created_by": self.owner,
        }
        values.update(overrides)
        return Workout.objects.create(workout_date=workout_date, **values)

    def test_counts_toward_the_local_week(self):
        # 00:30 UTC on Mon 2026-09-07 is 20:30 Sun 2026-09-06 in New York.
        workout = self.create_workout(datetime(2026, 9, 7, 0, 30))

        self.assertEqual(
            workout.workout_date_for_timezone, datetime(2026, 9, 6, 20, 30)
        )
        summary = WeeklySummary.objects.get(date=date(2026, 9, 6))
        self.assertEqual(summary.summary["workout"]["run"]["workouts"], 1)
        # The UTC week must not be touched.
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 13)).exists())

    def test_moving_a_workout_refreshes_both_local_weeks(self):
        workout = self.create_workout(datetime(2026, 9, 7, 0, 30))  # local week 09-06
        workout.workout_date = datetime(2026, 9, 14, 0, 30)  # local week 09-13
        workout.save()

        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())
        summary = WeeklySummary.objects.get(date=date(2026, 9, 13))
        self.assertEqual(summary.summary["workout"]["run"]["workouts"], 1)
