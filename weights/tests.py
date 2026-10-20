import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from alors.models import Comment, UserProfile

from .forms import TIME_ERROR, parse_seconds
from .models import (
    Exercise,
    WeightsWorkout,
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    WeightsWorkoutSuperset,
)

RESOLVED = (
    "equipment",
    "exercise_categories",
    "exercise_categorizations",
    "exercise_equipments",
    "primary_muscle_groups",
    "secondary_muscle_groups",
    "instructions",
)


class ExerciseJsonTests(SimpleTestCase):
    def test_returns_every_exercise(self):
        exercises = Exercise.get_exercises()

        self.assertEqual(len(exercises), 1274)
        self.assertEqual(exercises[0]["id"], "1")
        self.assertEqual(exercises[0]["attributes"]["name"], "Back Extensions")

    def test_resolves_known_relationships_in_place(self):
        relationships = Exercise.get_exercises()[0]["relationships"]

        for key in RESOLVED:
            self.assertNotIn("links", relationships[key])
            self.assertIsInstance(relationships[key]["data"], list)

    def test_keeps_links_for_relationships_without_bundled_data(self):
        relationships = Exercise.get_exercises()[0]["relationships"]

        self.assertIn("links", relationships["exercise_statistic"])

    def test_relationship_data_holds_the_related_resources(self):
        relationships = Exercise.get_exercises()[0]["relationships"]

        equipment = relationships["equipment"]["data"][0]
        self.assertEqual(equipment["type"], "equipment")
        self.assertIn("attributes", equipment)

        instructions = relationships["instructions"]["data"][0]
        self.assertIn("instructions", instructions["attributes"])

    def test_instance_method_matches_class_method(self):
        self.assertEqual(Exercise.get(1).get_exercise(), Exercise.get_exercises()[0])

    def test_get_returns_none_for_unknown_id(self):
        self.assertIsNone(Exercise.get(999999))

    def test_marks_only_timed_exercises_as_timed(self):
        self.assertTrue(Exercise.get(61).is_timed)
        self.assertFalse(Exercise.get(1).is_timed)

    def test_marks_only_unilateral_exercises_as_unilateral(self):
        self.assertTrue(Exercise.get(61).is_unilateral)
        self.assertFalse(Exercise.get(1).is_unilateral)

    def test_timed_ids_lists_every_timed_exercise(self):
        timed_ids = Exercise.timed_ids()

        self.assertIn(61, timed_ids)
        self.assertNotIn(1, timed_ids)
        self.assertEqual(len(timed_ids), 134)

    def test_returned_json_is_independent_of_the_cached_source(self):
        Exercise.get_exercises()[0]["relationships"]["equipment"]["data"].clear()

        self.assertTrue(
            Exercise.get_exercises()[0]["relationships"]["equipment"]["data"]
        )

    def test_catalogue_is_loaded_at_startup(self):
        from . import models

        self.assertEqual(models._catalogue.cache_info().currsize, 1)


class TimeEntryTests(SimpleTestCase):
    """Times are typed as one "m:ss" box rather than minutes and seconds."""

    def test_reads_minutes_and_seconds(self):
        self.assertEqual(parse_seconds("1:30"), 90)
        self.assertEqual(parse_seconds("0:45"), 45)
        self.assertEqual(parse_seconds("12:05"), 725)

    def test_reads_a_bare_number_as_seconds(self):
        self.assertEqual(parse_seconds("45"), 45)
        self.assertEqual(parse_seconds("90"), 90)

    def test_treats_a_blank_entry_as_no_time(self):
        self.assertIsNone(parse_seconds(""))
        self.assertIsNone(parse_seconds("   "))
        self.assertIsNone(parse_seconds(None))

    def test_ignores_whitespace(self):
        self.assertEqual(parse_seconds(" 1:30 "), 90)

    def test_rejects_anything_else(self):
        for value in ("later", "1:75", "1:2:3", "-1:30", "1:30pm"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_seconds(value)


class WeightsWorkoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lifter", password="secret"
        )
        self.workout = WeightsWorkout.objects.create(created_by=self.user)

    def test_records_owner_and_timestamps(self):
        self.workout.refresh_from_db()

        self.assertEqual(self.workout.created_by, self.user)
        self.assertIsNotNone(self.workout.created_at)
        self.assertIsNotNone(self.workout.updated_at)

    def test_a_workout_that_has_not_started_has_no_time(self):
        self.assertIsNone(self.workout.elapsed_seconds())
        self.assertIsNone(self.workout.elapsed)

    def test_the_time_counts_from_the_start(self):
        self.workout.started_at = timezone.now() - timedelta(minutes=5, seconds=30)
        self.workout.save()

        self.assertEqual(self.workout.elapsed_seconds(), 330)
        self.assertEqual(self.workout.elapsed, "5:30")

    def test_a_finished_workout_stops_at_its_finish_time(self):
        self.workout.started_at = timezone.now() - timedelta(hours=1)
        self.workout.finished_at = self.workout.started_at + timedelta(minutes=42)
        self.workout.completed = True
        self.workout.save()

        self.assertEqual(self.workout.elapsed_seconds(), 42 * 60)
        self.assertEqual(self.workout.elapsed, "42:00")

    def test_holds_multiple_exercises_in_position_order(self):
        second = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        first = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=1, position=0
        )

        self.assertEqual(list(self.workout.exercises.all()), [first, second])

    def test_get_exercises_returns_catalogue_json_in_order(self):
        WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=1, position=0
        )
        WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )

        exercises = self.workout.get_exercises()

        self.assertEqual([exercise["id"] for exercise in exercises], ["1", "2"])
        self.assertEqual(exercises[0]["attributes"]["name"], "Back Extensions")

    def test_exercise_entry_resolves_from_the_catalogue(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=1, position=0
        )

        self.assertEqual(entry.exercise.name, "Back Extensions")
        self.assertEqual(str(entry), "Back Extensions")

    def test_deleting_a_workout_deletes_its_exercises(self):
        WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=1, position=0
        )

        self.workout.delete()

        self.assertEqual(WeightsWorkoutExercise.objects.count(), 0)


class WeightsWorkoutSetTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="holder", password="pw")
        workout = WeightsWorkout.objects.create(created_by=user, title="Core")
        self.entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=61, position=0
        )

    def test_duration_is_shown_as_minutes_and_seconds(self):
        model_set = WeightsWorkoutSet.objects.create(
            entry=self.entry, duration_seconds=95, position=0
        )

        self.assertEqual(model_set.duration, "1:35")
        self.assertEqual(str(model_set), "1:35 min")

    def test_duration_is_none_without_a_time(self):
        model_set = WeightsWorkoutSet.objects.create(
            entry=self.entry, reps=8, position=0
        )

        self.assertIsNone(model_set.duration)
        self.assertEqual(str(model_set), "8 reps")

    def test_rest_is_shown_as_minutes_and_seconds(self):
        model_set = WeightsWorkoutSet.objects.create(
            entry=self.entry, reps=8, rest_seconds=45, position=0
        )

        self.assertEqual(model_set.rest, "0:45")

    def test_rest_is_none_without_a_rest(self):
        model_set = WeightsWorkoutSet.objects.create(
            entry=self.entry, reps=8, position=0
        )

        self.assertIsNone(model_set.rest)


def workout_rows_data(rows, title="Core", extra_rows=3):
    """POST data for a workout's exercise rows.

    ``rows`` is a list of ``(exercise_id, letter, [set field dicts])``. The
    formset renders a few empty rows after the real ones, so their sets'
    management forms are posted too.
    """
    total = max(len(rows), extra_rows)
    data = {
        "title": title,
        "exercises-TOTAL_FORMS": str(total),
        "exercises-INITIAL_FORMS": "0",
        "exercises-MIN_NUM_FORMS": "0",
        "exercises-MAX_NUM_FORMS": "1000",
    }
    for index in range(total):
        sets = []
        if index < len(rows):
            exercise_id, letter, sets = rows[index]
            data[f"exercises-{index}-exercise_id"] = str(exercise_id)
            data[f"exercises-{index}-superset"] = letter
        data[f"sets{index}-TOTAL_FORMS"] = str(len(sets))
        data[f"sets{index}-INITIAL_FORMS"] = "0"
        data[f"sets{index}-MIN_NUM_FORMS"] = "0"
        data[f"sets{index}-MAX_NUM_FORMS"] = "1000"
        for set_index, values in enumerate(sets):
            for name, value in values.items():
                data[f"sets{index}-{set_index}-{name}"] = str(value)
    return data


def workout_data(exercise_id, sets):
    """POST data for a workout holding one exercise row and its nested sets.

    ``sets`` is a list of dicts mapping set field names to values.
    """
    return workout_rows_data([(exercise_id, "", sets)])


class TimedExerciseViewTests(TestCase):
    TIMED_EXERCISE = 61
    UNTIMED_EXERCISE = 1
    _data = staticmethod(workout_data)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="planker", password="pw"
        )
        self.client.force_login(self.user)

    def _timed_entry(self, duration_seconds=95, **kwargs):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Core")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=self.TIMED_EXERCISE, position=0
        )
        WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=duration_seconds, position=0, **kwargs
        )
        return workout

    def test_add_saves_the_time_and_weight_without_reps(self):
        data = self._data(
            self.TIMED_EXERCISE,
            [{"duration": "1:30", "weight": "20"}, {"duration": "45"}],
        )

        response = self.client.post(reverse("weights:workout_add"), data)

        self.assertRedirects(response, reverse("weights:workout_list"))
        sets = list(WeightsWorkout.objects.get().exercises.get().sets.all())
        self.assertEqual([model_set.duration_seconds for model_set in sets], [90, 45])
        self.assertEqual([model_set.reps for model_set in sets], [None, None])
        self.assertEqual(sets[0].weight, Decimal("20.00"))

    def test_add_skips_a_timed_set_without_a_time(self):
        data = self._data(self.TIMED_EXERCISE, [{"duration": ""}])

        response = self.client.post(reverse("weights:workout_add"), data)

        self.assertRedirects(response, reverse("weights:workout_list"))
        self.assertTrue(WeightsWorkout.objects.exists())
        self.assertFalse(WeightsWorkoutSet.objects.exists())

    def test_a_time_may_be_given_as_plain_seconds(self):
        data = self._data(self.TIMED_EXERCISE, [{"duration": "90"}])

        self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(WeightsWorkoutSet.objects.get().duration_seconds, 90)

    def test_a_time_that_is_not_a_time_is_rejected(self):
        data = self._data(self.TIMED_EXERCISE, [{"duration": "half an hour"}])

        response = self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, TIME_ERROR)
        self.assertFalse(WeightsWorkout.objects.exists())

    def test_add_ignores_a_time_posted_for_an_untimed_exercise(self):
        data = self._data(self.UNTIMED_EXERCISE, [{"reps": 8, "duration": "5:00"}])

        self.client.post(reverse("weights:workout_add"), data)

        model_set = WeightsWorkoutSet.objects.get()
        self.assertEqual(model_set.reps, 8)
        self.assertIsNone(model_set.duration_seconds)

    def test_add_page_offers_a_time_per_set(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, 'name="sets0-0-duration"')
        self.assertContains(response, 'name="sets0-__prefix__-duration"')
        # Nothing is picked yet, so every row shows reps rather than a time.
        self.assertContains(response, 'class="col-2 timed-fields d-none"')
        self.assertNotContains(response, 'class="col-2 reps-fields d-none"')
        self.assertIn(self.TIMED_EXERCISE, response.context["timed_exercise_ids"])
        self.assertNotIn(self.UNTIMED_EXERCISE, response.context["timed_exercise_ids"])
        self.assertContains(response, 'id="timed-exercise-ids"')

    def test_edit_page_prefills_the_saved_time(self):
        workout = self._timed_entry()

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        set_form = response.context["groups"][0]["rows"][0]["set_formset"].forms[0]
        self.assertTrue(set_form.timed)
        self.assertEqual(set_form.initial["duration"], "1:35")
        self.assertContains(response, 'name="sets0-0-duration"')
        self.assertContains(response, 'data-timed="true"', count=1)

    def test_edit_keeps_the_time_when_no_other_change_is_made(self):
        workout = self._timed_entry()
        entry = workout.exercises.get()
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": "1",
            "exercises-INITIAL_FORMS": "1",
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
            "exercises-0-id": str(entry.pk),
            "exercises-0-exercise_id": str(self.TIMED_EXERCISE),
            "sets0-TOTAL_FORMS": "1",
            "sets0-INITIAL_FORMS": "1",
            "sets0-MIN_NUM_FORMS": "0",
            "sets0-MAX_NUM_FORMS": "1000",
            "sets0-0-id": str(entry.sets.get().pk),
            "sets0-0-duration": "1:35",
        }

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]), data
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        model_set = WeightsWorkoutSet.objects.get()
        self.assertEqual(model_set.duration_seconds, 95)
        self.assertIsNone(model_set.reps)
        self.assertEqual(WeightsWorkoutSet.objects.count(), 1)

    def test_list_shows_the_time_instead_of_reps(self):
        self._timed_entry(weight=Decimal("10"))

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "1:35 min @ 10.00 lb")
        self.assertNotContains(response, "reps")

    def test_list_still_shows_reps_for_untimed_sets(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=self.UNTIMED_EXERCISE, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "8 reps")


class ExerciseDetailTests(TestCase):
    """The description and picture a chosen exercise adds to its workout row."""

    EXERCISE = 1
    WITHOUT_INSTRUCTIONS = 2

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="detailer", password="w0rk0ut"
        )
        self.client.force_login(self.user)

    def test_returns_the_description_and_the_image(self):
        response = self.client.get(
            reverse("weights:exercise_detail", args=[self.EXERCISE])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], "1")
        self.assertEqual(payload["name"], "Back Extensions")
        self.assertIn("thighs on the forward pad", payload["description"])
        self.assertEqual(payload["image"], "/static/weights/exercises/24.jpg")

    def test_returns_nulls_for_an_exercise_without_them(self):
        response = self.client.get(
            reverse("weights:exercise_detail", args=[self.WITHOUT_INSTRUCTIONS])
        )

        payload = response.json()
        self.assertIsNone(payload["description"])
        self.assertIsNone(payload["image"])

    def test_unknown_exercise_is_not_found(self):
        response = self.client.get(reverse("weights:exercise_detail", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(
            reverse("weights:exercise_detail", args=[self.EXERCISE])
        )

        self.assertEqual(response.status_code, 302)

    def test_exercise_carries_its_description_and_image(self):
        exercise = Exercise.get(self.EXERCISE)

        self.assertIn("thighs on the forward pad", exercise.instructions)
        self.assertEqual(exercise.image_url, "/static/weights/exercises/24.jpg")

    def test_exercise_without_instructions_has_none(self):
        exercise = Exercise.get(self.WITHOUT_INSTRUCTIONS)

        self.assertIsNone(exercise.instructions)
        self.assertIsNone(exercise.image_url)

    def test_the_row_keeps_the_hook_the_js_finds_it_by(self):
        response = self.client.get(reverse("weights:workout_add"))

        # site.js looks a row up by this class before anything else.
        self.assertContains(response, 'class="exercise-row card mb-2"')
        self.assertContains(response, "data-exercise-detail")

    def test_workout_page_offers_the_details_of_a_chosen_exercise(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, 'id="exercise-detail-url"')
        self.assertContains(response, "exercise/__id__/")
        self.assertContains(response, 'data-detail-panel="description"')
        self.assertContains(response, 'data-detail-panel="image"')
        self.assertContains(response, 'data-detail="description"')
        self.assertContains(response, 'data-detail="image"')
        # One set of buttons for the row on screen, one in the JS row template.
        self.assertContains(response, "js-toggle-detail", count=4)

    def test_workout_page_rows_start_without_details(self):
        response = self.client.get(reverse("weights:workout_add"))

        # The panels appear once the row's exercise is fetched, and start shut.
        # The toggles carry "data-detail"; the block they sit in is marked up
        # separately so the two never collide.
        html = response.content.decode()
        self.assertRegex(
            html, r'class="exercise-detail[^"]*d-none"[^>]*data-exercise-detail'
        )
        for panel in ("description", "image"):
            self.assertRegex(
                html,
                rf'class="card card-body[^"]*d-none"[^>]*data-detail-panel="{panel}"',
            )


class RestPeriodTests(TestCase):
    EXERCISE = 1

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="resty", password="pw"
        )
        self.client.force_login(self.user)

    def _entry(self, **kwargs):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=self.EXERCISE, position=0
        )
        return workout, entry

    def _input_value(self, html, name):
        """The rendered value of the input with this name, if it has one."""
        match = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
        return match.group(1) if match else None

    def test_add_page_prefills_the_default_rest(self):
        response = self.client.get(reverse("weights:workout_add"))

        html = response.content.decode()
        self.assertEqual(self._input_value(html, "sets0-0-rest"), "0:45")
        self.assertEqual(self._input_value(html, "sets0-__prefix__-rest"), "0:45")
        # The times are single boxes, empty until they are filled in.
        self.assertIsNone(self._input_value(html, "sets0-0-duration"))
        self.assertIsNone(self._input_value(html, "sets0-__prefix__-duration"))

    def test_add_saves_the_rest(self):
        data = workout_data(
            self.EXERCISE,
            [{"reps": 8, "rest": "1:30"}, {"reps": 8}],
        )

        self.client.post(reverse("weights:workout_add"), data)

        entry = WeightsWorkout.objects.get().exercises.get()
        self.assertEqual(
            [model_set.rest_seconds for model_set in entry.sets.all()], [90, None]
        )

    def test_add_saves_the_defaulted_rest(self):
        data = workout_data(self.EXERCISE, [{"reps": 8, "rest": "45"}])

        self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(WeightsWorkoutSet.objects.get().rest_seconds, 45)

    def test_a_rest_may_be_given_as_plain_seconds(self):
        data = workout_data(self.EXERCISE, [{"reps": 8, "rest": "90"}])

        self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(WeightsWorkoutSet.objects.get().rest_seconds, 90)

    def test_a_rest_that_is_not_a_time_is_rejected(self):
        data = workout_data(self.EXERCISE, [{"reps": 8, "rest": "ages"}])

        response = self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, TIME_ERROR)
        self.assertFalse(WeightsWorkoutSet.objects.exists())

    def test_timed_sets_keep_their_rest(self):
        data = workout_data(
            61,
            [
                {
                    "duration": "1:30",
                    "weight": "20",
                    "rest": "1:15",
                }
            ],
        )

        self.client.post(reverse("weights:workout_add"), data)

        model_set = WeightsWorkoutSet.objects.get()
        self.assertEqual(model_set.duration_seconds, 90)
        self.assertEqual(model_set.rest_seconds, 75)

    def test_edit_page_prefills_the_saved_rest(self):
        workout, entry = self._entry()
        WeightsWorkoutSet.objects.create(
            entry=entry, reps=8, rest_seconds=90, position=0
        )

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        set_form = response.context["groups"][0]["rows"][0]["set_formset"].forms[0]
        self.assertEqual(set_form.initial["rest"], "1:30")

    def test_edit_clears_the_rest_when_blanked(self):
        workout, entry = self._entry()
        model_set = WeightsWorkoutSet.objects.create(
            entry=entry, reps=8, rest_seconds=90, position=0
        )
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": "1",
            "exercises-INITIAL_FORMS": "1",
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
            "exercises-0-id": str(entry.pk),
            "exercises-0-exercise_id": str(self.EXERCISE),
            "sets0-TOTAL_FORMS": "1",
            "sets0-INITIAL_FORMS": "1",
            "sets0-MIN_NUM_FORMS": "0",
            "sets0-MAX_NUM_FORMS": "1000",
            "sets0-0-id": str(model_set.pk),
            "sets0-0-reps": "8",
            "sets0-0-rest": "",
        }

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]), data
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        model_set.refresh_from_db()
        self.assertIsNone(model_set.rest_seconds)

    def test_list_shows_the_rest(self):
        _, entry = self._entry()
        WeightsWorkoutSet.objects.create(
            entry=entry, reps=8, rest_seconds=45, position=0
        )

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "8 reps (0:45 rest)")

    def test_duplicating_copies_the_rest(self):
        workout, entry = self._entry()
        WeightsWorkoutSet.objects.create(
            entry=entry, reps=8, rest_seconds=90, position=0
        )

        self.client.post(reverse("weights:workout_duplicate", args=[workout.pk]))

        duplicate = WeightsWorkout.objects.exclude(pk=workout.pk).get()
        self.assertEqual(duplicate.exercises.get().sets.get().rest_seconds, 90)


class SupersetTests(TestCase):
    FIRST_EXERCISE = 1
    SECOND_EXERCISE = 2

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="supersetter", password="pw"
        )
        self.client.force_login(self.user)

    def _superset(self, letter="A", rest_seconds=90, exercises=(1, 2)):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        superset = WeightsWorkoutSuperset.objects.create(
            workout=workout, letter=letter, rest_seconds=rest_seconds
        )
        entries = [
            WeightsWorkoutExercise.objects.create(
                workout=workout,
                exercise_id=exercise_id,
                position=position,
                superset=superset,
            )
            for position, exercise_id in enumerate(exercises)
        ]
        return workout, superset, entries

    def test_grouped_exercises_share_a_superset(self):
        data = workout_rows_data(
            [
                (self.FIRST_EXERCISE, "A", [{"reps": 8}]),
                (self.SECOND_EXERCISE, "A", [{"reps": 10}]),
            ]
        )
        data["superset-A-rest"] = "1:30"

        self.client.post(reverse("weights:workout_add"), data)

        workout = WeightsWorkout.objects.get()
        superset = workout.supersets.get()
        self.assertEqual((superset.letter, superset.rest_seconds), ("A", 90))
        self.assertEqual(
            [entry.superset_id for entry in workout.exercises.all()],
            [superset.pk, superset.pk],
        )

    def test_a_rest_that_is_not_a_time_is_ignored(self):
        data = workout_rows_data(
            [
                (self.FIRST_EXERCISE, "A", [{"reps": 8}]),
                (self.SECOND_EXERCISE, "A", [{"reps": 10}]),
            ]
        )
        data["superset-A-rest"] = "ages"

        self.client.post(reverse("weights:workout_add"), data)

        self.assertIsNone(WeightsWorkout.objects.get().supersets.get().rest_seconds)

    def test_each_group_is_kept_apart(self):
        data = workout_rows_data(
            [
                (self.FIRST_EXERCISE, "A", [{"reps": 8}]),
                (self.SECOND_EXERCISE, "A", [{"reps": 8}]),
                (3, "B", [{"reps": 8}]),
                (4, "B", [{"reps": 8}]),
            ]
        )
        data["superset-A-rest"] = "60"
        data["superset-B-rest"] = "90"

        self.client.post(reverse("weights:workout_add"), data)

        workout = WeightsWorkout.objects.get()
        self.assertEqual(
            {
                superset.letter: superset.rest_seconds
                for superset in workout.supersets.all()
            },
            {"A": 60, "B": 90},
        )
        self.assertEqual(
            [entry.superset.letter for entry in workout.exercises.all()],
            ["A", "A", "B", "B"],
        )

    def test_a_lone_letter_is_not_a_superset(self):
        data = workout_rows_data([(self.FIRST_EXERCISE, "A", [{"reps": 8}])])

        self.client.post(reverse("weights:workout_add"), data)

        workout = WeightsWorkout.objects.get()
        self.assertFalse(workout.supersets.exists())
        self.assertIsNone(workout.exercises.get().superset_id)

    def test_ungrouped_workouts_have_no_supersets(self):
        data = workout_rows_data(
            [
                (self.FIRST_EXERCISE, "", [{"reps": 8}]),
                (self.SECOND_EXERCISE, "", [{"reps": 8}]),
            ]
        )

        self.client.post(reverse("weights:workout_add"), data)

        self.assertFalse(WeightsWorkoutSuperset.objects.exists())

    def test_members_keep_no_rest_of_their_own(self):
        data = workout_rows_data(
            [
                (self.FIRST_EXERCISE, "A", [{"reps": 8, "rest": "0:45"}]),
                (self.SECOND_EXERCISE, "A", [{"reps": 8, "rest": "0:45"}]),
            ]
        )

        self.client.post(reverse("weights:workout_add"), data)

        self.assertEqual(
            [model_set.rest_seconds for model_set in WeightsWorkoutSet.objects.all()],
            [None, None],
        )

    def test_members_that_keep_no_sets_lose_their_rest_too(self):
        workout, _, entries = self._superset()
        model_set = WeightsWorkoutSet.objects.create(
            entry=entries[0], reps=8, rest_seconds=45, position=0
        )
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": "2",
            "exercises-INITIAL_FORMS": "2",
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
            "superset-A-rest": "1:30",
        }
        for position, entry in enumerate(entries):
            data[f"exercises-{position}-id"] = str(entry.pk)
            data[f"exercises-{position}-exercise_id"] = str(entry.exercise_id)
            data[f"exercises-{position}-superset"] = "A"
            # The set row is not posted, so the saved one is left alone.
            data[f"sets{position}-TOTAL_FORMS"] = "0"
            data[f"sets{position}-INITIAL_FORMS"] = "0"
            data[f"sets{position}-MIN_NUM_FORMS"] = "0"
            data[f"sets{position}-MAX_NUM_FORMS"] = "1000"

        self.client.post(reverse("weights:workout_edit", args=[workout.pk]), data)

        model_set.refresh_from_db()
        self.assertEqual(model_set.reps, 8)
        self.assertIsNone(model_set.rest_seconds)

    def test_ungrouping_a_workout_drops_its_supersets(self):
        workout, superset, entries = self._superset()
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": "2",
            "exercises-INITIAL_FORMS": "2",
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
        }
        for position, entry in enumerate(entries):
            data[f"exercises-{position}-id"] = str(entry.pk)
            data[f"exercises-{position}-exercise_id"] = str(entry.exercise_id)
            data[f"exercises-{position}-superset"] = ""
            data[f"sets{position}-TOTAL_FORMS"] = "0"
            data[f"sets{position}-INITIAL_FORMS"] = "0"
            data[f"sets{position}-MIN_NUM_FORMS"] = "0"
            data[f"sets{position}-MAX_NUM_FORMS"] = "1000"

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]), data
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        self.assertFalse(WeightsWorkoutSuperset.objects.exists())
        self.assertIsNone(
            WeightsWorkoutExercise.objects.get(pk=entries[0].pk).superset_id
        )

    def test_edit_page_shows_the_group_and_its_rest(self):
        workout, _, _ = self._superset(rest_seconds=90)

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        group = response.context["groups"][0]
        self.assertEqual(group["letter"], "A")
        self.assertEqual(group["rest"], "1:30")
        self.assertContains(response, 'name="superset-A-rest"')
        self.assertContains(response, 'value="1:30"')
        self.assertContains(response, 'data-superset="A"')
        self.assertContains(response, "js-superset-letter")

    def test_members_hide_their_own_rest_inputs(self):
        workout, _, _ = self._superset()

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        self.assertContains(response, 'class="col-2 rest-fields d-none"')

    def test_add_page_offers_the_superset_controls(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, "js-superset-handle")
        self.assertContains(response, 'id="empty-superset-header"')
        self.assertContains(response, "as a superset")

    def test_list_shows_the_superset_and_its_rest(self):
        workout, _, entries = self._superset(rest_seconds=90)
        WeightsWorkoutSet.objects.create(entry=entries[0], reps=8, position=0)

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "Superset A")
        self.assertContains(response, "1:30 rest at the end of each round")
        self.assertContains(response, "8 reps")

    def test_duplicating_copies_the_supersets(self):
        workout, _, _ = self._superset(rest_seconds=75)

        self.client.post(reverse("weights:workout_duplicate", args=[workout.pk]))

        duplicate = WeightsWorkout.objects.exclude(pk=workout.pk).get()
        copy = duplicate.supersets.get()
        self.assertEqual((copy.letter, copy.rest_seconds), ("A", 75))
        self.assertEqual(
            [entry.superset_id for entry in duplicate.exercises.all()],
            [copy.pk, copy.pk],
        )

    def test_exercise_groups_keep_solo_rows_in_order(self):
        workout, superset, entries = self._superset(exercises=(1, 2))
        solo = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=3, position=2
        )

        groups = workout.exercise_groups()

        self.assertEqual(
            [group.letter if group else None for group, _ in groups], ["A", None]
        )
        self.assertEqual(
            [entry.pk for _, group in groups for entry in group],
            [entries[0].pk, entries[1].pk, solo.pk],
        )

    def test_deleting_a_superset_leaves_its_exercises(self):
        _, superset, entries = self._superset()

        superset.delete()

        self.assertIsNone(
            WeightsWorkoutExercise.objects.get(pk=entries[0].pk).superset_id
        )
        self.assertTrue(
            WeightsWorkout.objects.filter(pk=entries[0].workout_id).exists()
        )

    def test_deleting_a_workout_deletes_its_supersets(self):
        workout, _, _ = self._superset()

        workout.delete()

        self.assertFalse(WeightsWorkoutSuperset.objects.exists())


class DoWorkoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lifter", password="pw"
        )
        self.client.force_login(self.user)

    def _plan(self, superset=False):
        """A plan with two exercises, three sets and an optional superset."""
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        group = None
        if superset:
            group = WeightsWorkoutSuperset.objects.create(
                workout=workout, letter="A", rest_seconds=90
            )
        first = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0, superset=group
        )
        WeightsWorkoutSet.objects.create(
            entry=first,
            reps=8,
            weight=Decimal("50.5"),
            rest_seconds=45,
            position=0,
        )
        WeightsWorkoutSet.objects.create(entry=first, reps=10, position=1)
        second = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=61, position=1, superset=group
        )
        WeightsWorkoutSet.objects.create(
            entry=second, duration_seconds=90, weight=Decimal("20"), position=0
        )
        return workout

    def _do(self, workout):
        self.client.post(reverse("weights:workout_do", args=[workout.pk]))
        return WeightsWorkout.objects.exclude(pk=workout.pk).get()

    def _payload(self, workout, sets=None):
        """POST data for a workout's edit page, as the page renders it.

        ``sets`` maps ``(exercise index, set index)`` to extra fields.
        """
        entries = list(workout.exercises.all())
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": str(len(entries)),
            "exercises-INITIAL_FORMS": str(len(entries)),
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
        }
        for group in workout.supersets.all():
            data[f"superset-{group.letter}-rest"] = group.rest or ""
        for index, entry in enumerate(entries):
            data[f"exercises-{index}-id"] = str(entry.pk)
            data[f"exercises-{index}-exercise_id"] = str(entry.exercise_id)
            data[f"exercises-{index}-superset"] = (
                entry.superset.letter if entry.superset_id else ""
            )
            model_sets = list(entry.sets.all())
            data[f"sets{index}-TOTAL_FORMS"] = str(len(model_sets))
            data[f"sets{index}-INITIAL_FORMS"] = str(len(model_sets))
            data[f"sets{index}-MIN_NUM_FORMS"] = "0"
            data[f"sets{index}-MAX_NUM_FORMS"] = "1000"
            for set_index, model_set in enumerate(model_sets):
                prefix = f"sets{index}-{set_index}"
                data[f"{prefix}-id"] = str(model_set.pk)
                data[f"{prefix}-reps"] = str(model_set.reps or "")
                data[f"{prefix}-weight"] = str(model_set.weight or "")
                data[f"{prefix}-duration"] = model_set.duration or ""
                data[f"{prefix}-rest"] = model_set.rest or ""
                data[f"{prefix}-completed"] = "on" if model_set.completed else ""
                data.update(
                    {
                        f"{prefix}-{name}": str(value)
                        for name, value in (sets or {})
                        .get((index, set_index), {})
                        .items()
                    }
                )
        return data

    def test_do_copies_the_plan_into_an_actual_workout(self):
        plan = self._plan(superset=True)
        WeightsWorkoutSet.objects.filter(entry__workout=plan).update(completed=True)

        response = self.client.post(reverse("weights:workout_do", args=[plan.pk]))

        actual = WeightsWorkout.objects.exclude(pk=plan.pk).get()
        self.assertRedirects(
            response, reverse("weights:workout_perform", args=[actual.pk])
        )
        self.assertEqual(actual.plan, plan)
        self.assertTrue(actual.is_actual)
        self.assertEqual(actual.created_by, self.user)
        self.assertEqual(actual.title, plan.title)
        self.assertNotIn("(copy)", actual.title)
        self.assertEqual(actual.set_count(), 3)
        group = actual.supersets.get()
        self.assertEqual((group.letter, group.rest_seconds), ("A", 90))
        self.assertEqual(
            [
                (entry.exercise_id, entry.position, entry.superset.letter)
                for entry in actual.exercises.all()
            ],
            [(1, 0, "A"), (61, 1, "A")],
        )
        self.assertEqual(
            [
                (model_set.reps, model_set.weight, model_set.duration_seconds)
                for model_set in actual.exercises.first().sets.all()
            ],
            [(8, Decimal("50.5"), None), (10, None, None)],
        )
        self.assertEqual(actual.completed_set_count(), 0)

    def test_working_through_the_workout_leaves_the_plan_alone(self):
        plan = self._plan(superset=True)
        actual = self._do(plan)

        self.client.post(
            reverse("weights:workout_edit", args=[actual.pk]),
            self._payload(actual, sets={(0, 0): {"completed": "on", "reps": "1"}}),
        )

        plan.refresh_from_db()
        self.assertFalse(plan.is_actual)
        self.assertEqual(plan.set_count(), 3)
        self.assertEqual(plan.completed_set_count(), 0)
        self.assertEqual(
            [model_set.reps for model_set in plan.exercises.first().sets.all()],
            [8, 10],
        )

    def test_do_requires_post(self):
        plan = self._plan()

        response = self.client.get(reverse("weights:workout_do", args=[plan.pk]))

        self.assertRedirects(response, reverse("weights:workout_edit", args=[plan.pk]))
        self.assertEqual(WeightsWorkout.objects.count(), 1)

    def test_doing_an_actual_workout_again_starts_from_its_plan(self):
        plan = self._plan()
        actual = self._do(plan)

        response = self.client.post(reverse("weights:workout_do", args=[actual.pk]))

        again = WeightsWorkout.objects.exclude(pk__in=[plan.pk, actual.pk]).get()
        self.assertRedirects(
            response, reverse("weights:workout_perform", args=[again.pk])
        )
        self.assertEqual(again.plan, plan)

    def test_actual_page_ticks_sets_off_and_counts_them(self):
        actual = self._do(self._plan())

        response = self.client.get(reverse("weights:workout_edit", args=[actual.pk]))

        self.assertContains(response, 'name="sets0-0-completed"')
        self.assertContains(response, 'name="sets0-__prefix__-completed"')
        self.assertContains(response, "0 of 3 sets done")
        self.assertNotContains(response, "Start workout")

    def test_the_rows_the_js_adds_offer_the_done_boxes_too(self):
        actual = self._do(self._plan())

        response = self.client.get(reverse("weights:workout_edit", args=[actual.pk]))

        # The row the JS clones is built from the same partial as the saved
        # rows, so it carries the "done" boxes of a workout being done.
        self.assertContains(response, 'name="sets0-0-completed"')
        self.assertContains(response, 'name="sets__exercise__-__prefix__-completed"')

    def test_a_plan_offers_no_done_boxes_at_all(self):
        plan = self._plan()

        response = self.client.get(reverse("weights:workout_edit", args=[plan.pk]))

        self.assertNotContains(response, "-completed")

    def test_plan_page_does_not_offer_to_start_the_workout(self):
        plan = self._plan()

        response = self.client.get(reverse("weights:workout_edit", args=[plan.pk]))

        self.assertNotContains(response, "Start workout")
        self.assertNotContains(
            response, f'action="{reverse("weights:workout_do", args=[plan.pk])}"'
        )
        self.assertNotContains(response, "-completed")

    def test_ticking_a_set_off_is_saved(self):
        actual = self._do(self._plan())

        response = self.client.post(
            reverse("weights:workout_edit", args=[actual.pk]),
            self._payload(actual, sets={(0, 0): {"completed": "on"}}),
        )

        self.assertRedirects(
            response, reverse("weights:workout_edit", args=[actual.pk])
        )
        self.assertEqual(actual.completed_set_count(), 1)
        self.assertEqual(
            [model_set.completed for model_set in actual.exercises.first().sets.all()],
            [True, False],
        )

    def test_values_can_be_changed_and_a_set_deleted(self):
        actual = self._do(self._plan())
        changed, dropped = list(actual.exercises.first().sets.all())

        response = self.client.post(
            reverse("weights:workout_edit", args=[actual.pk]),
            self._payload(
                actual,
                sets={
                    (0, 0): {"reps": "5", "weight": "55"},
                    (0, 1): {"DELETE": "on"},
                },
            ),
        )

        self.assertRedirects(
            response, reverse("weights:workout_edit", args=[actual.pk])
        )
        changed.refresh_from_db()
        self.assertEqual((changed.reps, changed.weight), (5, Decimal("55.00")))
        self.assertFalse(WeightsWorkoutSet.objects.filter(pk=dropped.pk).exists())
        self.assertEqual(actual.set_count(), 2)

    def test_a_plan_keeps_the_done_flags_it_was_saved_with(self):
        plan = self._plan()
        WeightsWorkoutSet.objects.filter(entry__workout=plan).update(completed=True)

        self.client.post(
            reverse("weights:workout_edit", args=[plan.pk]), self._payload(plan)
        )

        self.assertEqual(WeightsWorkoutSet.objects.filter(completed=True).count(), 3)

    def test_duplicating_gives_a_planned_workout_with_nothing_ticked(self):
        plan = self._plan()
        actual = self._do(plan)
        WeightsWorkoutSet.objects.filter(entry__workout=actual).update(completed=True)

        self.client.post(reverse("weights:workout_duplicate", args=[actual.pk]))

        copy = WeightsWorkout.objects.exclude(pk__in=[plan.pk, actual.pk]).get()
        self.assertFalse(copy.is_actual)
        self.assertIsNone(copy.plan)
        self.assertEqual(copy.set_count(), 3)
        self.assertEqual(copy.completed_set_count(), 0)

    def test_an_actual_workout_stays_actual_without_its_plan(self):
        plan = self._plan()
        actual = self._do(plan)

        plan.delete()

        actual.refresh_from_db()
        self.assertIsNone(actual.plan_id)
        self.assertTrue(actual.is_actual)

    def test_list_offers_to_do_a_planned_workout(self):
        plan = self._plan()
        actual = self._do(plan)

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(
            response, f'action="{reverse("weights:workout_do", args=[plan.pk])}"'
        )
        self.assertNotContains(
            response, f'action="{reverse("weights:workout_do", args=[actual.pk])}"'
        )

    def test_list_shows_the_plan_not_the_actual_workout(self):
        plan = self._plan()
        actual = self._do(plan)
        first = actual.exercises.first().sets.first()
        first.completed = True
        first.save()

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, plan.title)
        self.assertNotContains(response, "1 of 3 sets done")
        self.assertNotContains(response, f"weights/{actual.pk}/do/")

    def test_a_set_can_be_ticked_off_and_removed_from_an_actual_workout(self):
        actual = self._do(self._plan())

        response = self.client.get(reverse("weights:workout_edit", args=[actual.pk]))

        self.assertContains(
            response, 'name="sets0-0-completed" class="form-check-input"'
        )
        self.assertContains(response, 'name="sets0-0-DELETE" class="d-none"')
        self.assertContains(response, "js-remove-set")


class WorkoutStepTests(TestCase):
    """The order a workout is done in, supersets included."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="stepper", password="w0rk0ut"
        )
        self.workout = WeightsWorkout.objects.create(created_by=user, title="Leg day")

    def _entry(self, exercise_id, position, sets, superset=None):
        """An exercise row holding one set per dict of values."""
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout,
            exercise_id=exercise_id,
            position=position,
            superset=superset,
        )
        for index, values in enumerate(sets):
            WeightsWorkoutSet.objects.create(entry=entry, position=index, **values)
        return entry

    def test_plain_exercises_are_done_set_by_set(self):
        first = self._entry(1, 0, [{"reps": 8, "rest_seconds": 45}, {"reps": 8}])
        second = self._entry(2, 1, [{"reps": 10}])

        steps = self.workout.steps()

        self.assertEqual(
            [(step.entry, step.number, step.of) for step in steps],
            [(first, 1, 2), (first, 2, 2), (second, 1, 1)],
        )
        # Each set carries its own rest, and nothing else does.
        self.assertEqual([step.rest_seconds for step in steps], [45, None, None])
        self.assertEqual(steps[0].rest, "0:45")
        self.assertIsNone(steps[0].superset)
        self.assertIsNone(steps[0].round)

    def test_a_superset_is_done_in_rounds_with_one_rest_each(self):
        group = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        first = self._entry(1, 0, [{"reps": 8}, {"reps": 8}], superset=group)
        second = self._entry(
            2, 1, [{"reps": 10}, {"reps": 10}, {"reps": 10}], superset=group
        )

        steps = self.workout.steps()

        self.assertEqual(
            [(step.entry, step.number, step.round) for step in steps],
            [
                (first, 1, 1),
                (second, 1, 1),
                (first, 2, 2),
                (second, 2, 2),
                (second, 3, 3),
            ],
        )
        self.assertEqual([step.of for step in steps], [2, 3, 2, 3, 3])
        self.assertEqual([step.rounds for step in steps], [3, 3, 3, 3, 3])
        # The rest lands on the last set of each round, not after every set.
        self.assertEqual(
            [step.rest_seconds for step in steps], [None, 90, None, 90, 90]
        )
        self.assertEqual(steps[1].rest, "1:30")
        self.assertEqual(steps[1].superset, group)
        # Each set knows where it comes in the workout, rounds and all, so the
        # page can follow the order it is done in rather than its own layout.
        self.assertEqual([step.order for step in steps], [0, 1, 2, 3, 4])

    def test_sets_with_nothing_to_do_are_left_out(self):
        self._entry(1, 0, [{"reps": None}, {"reps": 8}])

        steps = self.workout.steps()

        self.assertEqual([step.set.reps for step in steps], [8])
        self.assertEqual(steps[0].number, 2)

    def test_step_groups_hold_the_sets_of_one_exercise_each(self):
        first = self._entry(1, 0, [{"reps": 8}, {"reps": 8}])
        second = self._entry(2, 1, [{"reps": 10}])

        groups = self.workout.step_groups()

        self.assertEqual(
            [(entry, [step.set.reps for step in group]) for entry, group in groups],
            [(first, [8, 8]), (second, [10])],
        )

    def test_a_superset_comes_back_as_a_group_for_each_exercise(self):
        superset = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        first = self._entry(1, 0, [{"reps": 8}, {"reps": 8}], superset=superset)
        second = self._entry(2, 1, [{"reps": 10}, {"reps": 10}], superset=superset)

        groups = self.workout.step_groups()

        self.assertEqual([entry for entry, group in groups], [first, second])
        self.assertEqual([len(group) for entry, group in groups], [2, 2])

    def test_a_workout_with_nothing_to_do_has_no_groups(self):
        self.assertEqual(self.workout.step_groups(), [])

    def test_timed_sets_are_marked_as_timed(self):
        self._entry(61, 0, [{"duration_seconds": 90}])

        step = self.workout.steps()[0]

        self.assertTrue(step.timed)
        self.assertIsNone(step.rest_seconds)

    def test_a_timed_unilateral_set_is_done_on_both_sides(self):
        self._entry(61, 0, [{"duration_seconds": 90}])

        step = self.workout.steps()[0]

        self.assertTrue(step.unilateral)
        self.assertEqual(step.sides, 2)

    def test_a_timed_set_on_both_sides_at_once_has_one_side(self):
        self._entry(62, 0, [{"duration_seconds": 90}])

        step = self.workout.steps()[0]

        self.assertFalse(step.unilateral)
        self.assertEqual(step.sides, 1)

    def test_a_step_knows_when_it_is_done(self):
        self._entry(1, 0, [{"reps": 8, "completed": True}])

        self.assertTrue(self.workout.steps()[0].done)

    def test_repr_names_the_step(self):
        entry = self._entry(1, 0, [{"reps": 8}])

        self.assertEqual(
            repr(self.workout.steps()[0]), f"<WorkoutStep {entry} set 1 of 1>"
        )


class PerformWorkoutTests(TestCase):
    """Doing a workout: one set at a time, with the rest to hand."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="doer", password="w0rk0ut"
        )
        self.client.force_login(self.user)
        self.workout = WeightsWorkout.objects.create(
            created_by=self.user, title="Leg day", is_actual=True
        )
        self.entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=1, position=0
        )
        self.first = WeightsWorkoutSet.objects.create(
            entry=self.entry,
            reps=8,
            weight=Decimal("50.00"),
            rest_seconds=45,
            position=0,
        )
        self.second = WeightsWorkoutSet.objects.create(
            entry=self.entry, reps=10, position=1
        )

    def url(self):
        return reverse("weights:workout_perform", args=[self.workout.pk])

    def post(self, action, model_set=None, ajax=False, **extra):
        data = {"set": (model_set or self.first).pk, "action": action}
        data.update(extra)
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
        return self.client.post(self.url(), data, **headers)

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 302)

    def test_a_plan_is_edited_rather_than_done(self):
        plan = WeightsWorkout.objects.create(created_by=self.user, title="Plan")

        response = self.client.get(reverse("weights:workout_perform", args=[plan.pk]))

        self.assertRedirects(response, reverse("weights:workout_edit", args=[plan.pk]))

    def test_the_workout_is_shown_one_set_at_a_time(self):
        response = self.client.get(self.url())

        self.assertEqual(response.context["current_index"], 0)
        self.assertEqual(
            (response.context["done_count"], response.context["total_count"]),
            (0, 2),
        )
        self.assertContains(response, "Leg day")
        self.assertContains(response, "0</span> of 2 sets")
        self.assertContains(response, f'name="set-{self.first.pk}-reps" form="log-set"')
        self.assertContains(
            response, f'name="set-{self.second.pk}-reps" form="log-set"'
        )
        self.assertNotContains(response, "progress-bar")

    def test_it_opens_on_the_first_set_still_to_do(self):
        self.first.completed = True
        self.first.save()

        response = self.client.get(self.url())

        self.assertEqual(response.context["current_index"], 1)
        self.assertEqual(response.context["done_count"], 1)

    def test_the_page_can_open_on_a_chosen_exercise(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)

        response = self.client.get(self.url() + f"?entry={other.pk}")

        self.assertEqual(response.context["current_index"], 2)
        self.assertEqual(
            [group["current"] for group in response.context["step_groups"]],
            [False, True],
        )

    def test_a_finished_chosen_exercise_hands_the_page_on(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(
            entry=other, reps=10, position=0, completed=True
        )

        response = self.client.get(self.url() + f"?entry={other.pk}")

        self.assertEqual(response.context["current_index"], 0)

    def test_a_superset_step_carries_its_round_and_rest(self):
        group = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        self.entry.superset = group
        self.entry.save()
        self.second.superset = group
        self.second.save()

        response = self.client.get(self.url())

        self.assertContains(response, "Superset A")
        self.assertContains(response, 'data-round="1"')
        self.assertContains(response, 'data-round="2"')
        self.assertContains(response, 'data-step-rest="90"')

    def test_ticking_a_set_off(self):
        response = self.post("complete")

        self.assertRedirects(response, self.url())
        self.first.refresh_from_db()
        self.assertTrue(self.first.completed)

    def test_ticking_a_set_off_in_the_background(self):
        response = self.post("complete", ajax=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "action": "complete",
                "deleted": False,
                "completed": True,
                "set": self.first.pk,
                "done_count": 1,
                "total_count": 2,
                "finished": False,
                "errors": {},
            },
        )
        self.first.refresh_from_db()
        self.assertTrue(self.first.completed)

    def test_the_page_shows_the_time_spent_so_far_instead_of_a_bar(self):
        self.workout.started_at = timezone.now() - timedelta(minutes=2)
        self.workout.save()

        response = self.client.get(self.url())

        self.assertContains(response, 'data-elapsed="120"')
        self.assertContains(response, ">2:00</span>")
        self.assertNotContains(response, "progress-bar")

    def test_a_finished_workout_shows_the_time_it_took(self):
        self.workout.started_at = timezone.now() - timedelta(hours=1)
        self.workout.finished_at = self.workout.started_at + timedelta(minutes=7)
        self.workout.completed = True
        self.workout.save()

        response = self.client.get(self.url())

        self.assertContains(response, 'data-elapsed="420"')
        self.assertContains(response, 'data-finished="true"')
        self.assertContains(response, ">7:00</span>")

    def test_the_page_offers_one_log_set_button(self):
        response = self.client.get(self.url())

        self.assertContains(response, "Log set")
        self.assertContains(response, 'name="action" value="log"')
        self.assertEqual(response.content.decode().count("Log set"), 1)
        self.assertNotContains(response, "Complete set")
        self.assertNotContains(response, "Undo this set")

    def test_only_the_exercise_being_done_is_on_show(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)

        response = self.client.get(self.url())

        content = response.content.decode()
        # One exercise on show, the other parked until it comes on.
        self.assertEqual(content.count("data-exercise-group"), 2)
        self.assertEqual(content.count("perform-exercise d-none"), 1)

    def _on_show(self, response):
        """The exercises the page puts in front of the user."""
        return re.findall(
            r'<div class="card perform-exercise(?![^"]*d-none)[^"]*"\s+'
            r'data-exercise-group="(\d+)"',
            response.content.decode(),
        )

    def test_a_superset_works_its_way_round_its_exercises(self):
        group = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        self.entry.superset = group
        self.entry.save()
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1, superset=group
        )
        other_set = WeightsWorkoutSet.objects.create(entry=other, reps=12, position=0)

        response = self.client.get(self.url())

        # The sets are numbered as they are done: one from each exercise, then
        # back to the first for the next round.
        self.assertEqual(
            [step.set.pk for step in self.workout.steps()],
            [self.first.pk, other_set.pk, self.second.pk],
        )
        for line in ('data-step="1"', 'data-round="1"', 'data-round="2"'):
            self.assertContains(response, line)
        # The round is done a set at a time, starting with the first exercise.
        self.assertEqual(self._on_show(response), [str(self.entry.pk)])

        self.post("log", self.first)

        # The first exercise's set is logged, so the next one in the superset
        # comes on; the first comes back for the next round.
        self.assertEqual(self._on_show(self.client.get(self.url())), [str(other.pk)])

    def test_the_page_badges_an_exercise_in_a_superset(self):
        group = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        self.entry.superset = group
        self.entry.save()
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=12, position=0)

        response = self.client.get(self.url())

        # The exercise in the superset says which one it is; the exercise on its
        # own has nothing to say.
        content = response.content.decode()
        self.assertContains(response, "Superset A")
        self.assertEqual(content.count("superset-badge"), 1)

    def test_an_exercise_with_every_set_logged_is_badged_as_completed(self):
        response = self.client.get(self.url())

        # The badge is on the card, but says nothing until the sets are done.
        self.assertContains(
            response,
            '<span class="badge bg-success d-none" data-done-badge>Completed</span>',
        )

        WeightsWorkoutSet.objects.filter(entry=self.entry).update(completed=True)

        response = self.client.get(self.url())

        self.assertContains(
            response,
            '<span class="badge bg-success" data-done-badge>Completed</span>',
        )

    def test_the_sets_are_laid_out_as_a_table(self):
        response = self.client.get(self.url())

        self.assertContains(response, 'class="table perform-sets"')
        self.assertContains(response, '<th scope="col">Reps</th>')
        self.assertContains(response, '<th scope="col">Weight (lb)</th>')
        # The set's values are inputs the log takes as it goes.
        self.assertContains(response, f'name="set-{self.first.pk}-reps" form="log-set"')
        self.assertContains(
            response, f'name="set-{self.first.pk}-weight" form="log-set"'
        )
        self.assertContains(response, 'value="8"')
        self.assertContains(response, 'value="50.00"')

    def test_each_set_has_a_plus_holding_its_own_actions(self):
        response = self.client.get(self.url())

        content = response.content.decode()
        # One "+" per set, each opening the actions under its own row.
        self.assertEqual(
            content.count('data-bs-toggle="collapse" href="#set-details-'), 2
        )
        for step in (self.first, self.second):
            self.assertContains(response, f'href="#set-details-{step.pk}"')
            self.assertContains(
                response, f'<tr id="set-details-{step.pk}" class="collapse">'
            )
        self.assertContains(
            response, '<span class="visually-hidden">Set actions</span>'
        )
        self.assertEqual(content.count('name="action" value="delete"'), 2)
        self.assertEqual(content.count('name="action" value="undo"'), 2)
        self.assertEqual(content.count('name="action" value="add"'), 2)
        self.assertContains(response, ">Delete</a>")
        self.assertContains(response, ">Reopen</a>")
        self.assertContains(response, ">Add another</a>")

    def test_adding_another_set_copies_it_after_the_last_one(self):
        response = self.post("add", model_set=self.first)

        self.assertRedirects(response, self.url())
        added = (
            self.entry.sets.exclude(pk=self.first.pk).exclude(pk=self.second.pk).get()
        )
        self.assertEqual(added.reps, self.first.reps)
        self.assertEqual(added.weight, self.first.weight)
        self.assertEqual(added.rest_seconds, self.first.rest_seconds)
        self.assertEqual(added.position, self.second.position + 1)
        self.assertFalse(added.completed)

    def test_adding_another_timed_set_keeps_its_time(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=0
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, weight=Decimal("20.00"), position=0
        )
        self.workout.exercises.exclude(pk=entry.pk).delete()

        self.post("add", model_set=timed)

        added = entry.sets.exclude(pk=timed.pk).get()
        self.assertEqual(added.duration_seconds, 90)
        self.assertEqual(added.weight, Decimal("20.00"))
        self.assertIsNone(added.reps)
        self.assertFalse(added.completed)

    def test_a_timed_exercise_is_labelled_time(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=1
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )

        response = self.client.get(self.url())

        self.assertContains(response, '<th scope="col">Time</th>')
        self.assertContains(response, f'name="set-{timed.pk}-duration" form="log-set"')
        self.assertContains(response, 'value="1:30"')

    def test_a_timed_set_offers_a_timer(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=1
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )

        response = self.client.get(self.url())

        # The set's own time is what the timer counts down.
        self.assertContains(response, f'data-timer="{timed.duration_seconds}"')
        self.assertContains(response, "data-timer-panel")
        self.assertContains(response, "data-timer-side")
        for label in ("Start", "Pause", "End"):
            self.assertContains(response, f">{label}</button>")
        self.assertNotContains(response, ">Stop</button>")
        self.assertNotContains(response, ">Cancel</button>")

    def test_a_timed_unilateral_set_is_counted_down_on_each_side(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=1
        )
        WeightsWorkoutSet.objects.create(entry=entry, duration_seconds=90, position=0)

        response = self.client.get(self.url())

        self.assertContains(response, 'data-sides="2"', count=1)

    def test_a_timed_set_done_on_both_sides_at_once_has_one_countdown(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=62, position=1
        )
        WeightsWorkoutSet.objects.create(entry=entry, duration_seconds=90, position=0)

        response = self.client.get(self.url())

        self.assertContains(response, 'data-sides="1"')
        self.assertNotContains(response, 'data-sides="2"')

    def test_a_set_counted_in_reps_has_no_timer_to_press(self):
        response = self.client.get(self.url())

        self.assertNotContains(response, 'data-timer="')
        self.assertContains(response, ">Log set</button>")
        self.assertNotContains(response, "Start timer")

    def test_a_timed_exercise_offers_to_start_its_timer(self):
        workout = WeightsWorkout.objects.create(
            created_by=self.user, title="Core", is_actual=True
        )
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=61, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, duration_seconds=90, position=0)

        response = self.client.get(
            reverse("weights:workout_perform", args=[workout.pk])
        )

        self.assertTrue(response.context["current_timed"])
        self.assertContains(response, ">Start timer</button>")
        self.assertContains(response, 'data-timed="true"')
        self.assertNotContains(response, "Log set")

    def test_an_exercise_image_can_back_its_card_in_the_full_list(self):
        response = self.client.get(self.url())

        self.assertContains(response, "has-exercise-image")
        self.assertContains(response, "--exercise-image")

    def test_logging_a_set_saves_the_values_typed_in(self):
        response = self.post(
            "log",
            ajax=True,
            **{f"set-{self.first.pk}-reps": "12", f"set-{self.first.pk}-weight": "60"},
        )

        self.assertTrue(response.json()["ok"])
        self.first.refresh_from_db()
        self.assertTrue(self.first.completed)
        self.assertEqual(self.first.reps, 12)
        self.assertEqual(self.first.weight, Decimal("60.00"))
        # Rest is not on the page, so the set keeps its own.
        self.assertEqual(self.first.rest_seconds, 45)

    def test_logging_a_timed_set_saves_the_time_typed_in(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=0
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )
        self.workout.exercises.exclude(pk=entry.pk).delete()

        response = self.post("log", ajax=True, **{f"set-{timed.pk}-duration": "1:20"})

        self.assertTrue(response.json()["ok"])
        timed.refresh_from_db()
        self.assertTrue(timed.completed)
        self.assertEqual(timed.duration_seconds, 80)
        self.assertIsNone(timed.reps)

    def test_ending_a_timer_logs_its_elapsed_time_and_completes_the_set(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=0
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )
        self.workout.exercises.exclude(pk=entry.pk).delete()

        response = self.post(
            "end",
            model_set=timed,
            ajax=True,
            **{f"set-{timed.pk}-duration": "0:35"},
        )

        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["set"], timed.pk)
        timed.refresh_from_db()
        self.assertTrue(timed.completed)
        self.assertEqual(timed.duration_seconds, 35)
        self.assertIsNone(timed.reps)

    def test_logging_a_time_that_is_not_a_time_logs_nothing(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=0
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )
        self.workout.exercises.exclude(pk=entry.pk).delete()

        response = self.post("log", ajax=True, **{f"set-{timed.pk}-duration": "ages"})

        self.assertFalse(response.json()["ok"])
        self.assertIn("duration", response.json()["errors"])
        timed.refresh_from_db()
        self.assertFalse(timed.completed)
        self.assertEqual(timed.duration_seconds, 90)

    def test_the_next_exercise_comes_on_when_the_first_is_finished(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)
        WeightsWorkoutSet.objects.filter(entry=self.entry).update(completed=True)

        response = self.client.get(self.url())

        self.assertEqual(
            [group["entry"] for group in response.context["step_groups"]],
            [self.entry, other],
        )
        self.assertEqual(
            [group["current"] for group in response.context["step_groups"]],
            [False, True],
        )
        self.assertEqual(response.context["current_index"], 2)

    def test_logging_a_set_ticks_off_the_first_one_still_to_do(self):
        # Posted from the second row, but the first set is the one still to do.
        response = self.post("log", model_set=self.second, ajax=True)

        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["set"], self.first.pk)
        self.assertEqual(response.json()["done_count"], 1)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertTrue(self.first.completed)
        self.assertFalse(self.second.completed)

    def test_logging_without_the_background_ticks_the_same_set_off(self):
        response = self.post("log")

        self.assertRedirects(response, self.url())
        self.first.refresh_from_db()
        self.assertTrue(self.first.completed)

    def test_the_page_offers_the_full_list_and_a_pick_of_exercise(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)

        response = self.client.get(self.url())

        # A link that opens every exercise, and a name that picks one out.
        self.assertContains(response, "Show all exercises")
        self.assertContains(response, "data-show-all")
        self.assertEqual(response.content.decode().count("data-pick"), 2)
        self.assertContains(response, f'data-exercise-group="{self.entry.pk}"')
        # Logging follows the picked exercise, so the page targets it.
        self.assertContains(response, '<input type="hidden" name="entry" value="">')

    def test_each_exercise_has_a_summary_for_the_full_list(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)
        WeightsWorkoutSet.objects.filter(pk=self.first.pk).update(completed=True)

        response = self.client.get(self.url())

        # One card per exercise, with its own line of how far along it is and
        # the way back into it.
        content = response.content.decode()
        self.assertContains(response, "card-title")
        self.assertContains(response, "perform-summary card-text")
        self.assertContains(response, "1 of 2 sets done")
        self.assertContains(response, "0 of 1 sets done")
        self.assertEqual(content.count('class="card-footer"'), 2)
        self.assertContains(response, "Work on this exercise")

    def test_the_full_list_says_what_was_done_for_an_exercise(self):
        WeightsWorkoutSet.objects.filter(pk=self.first.pk).update(completed=True)
        WeightsWorkoutSet.objects.filter(pk=self.second.pk).update(
            completed=True, weight=Decimal("52.50")
        )

        response = self.client.get(self.url())

        # Each logged set is written back the way it was done.
        self.assertContains(response, "data-performed>8 @ 50 lb, 10 @ 52.5 lb</p>")

    def test_the_full_list_says_what_was_done_for_a_timed_exercise(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=1
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, weight=Decimal("20.00"), position=0
        )
        WeightsWorkoutSet.objects.filter(pk=timed.pk).update(completed=True)

        response = self.client.get(self.url())

        self.assertContains(response, "data-performed>1:30 @ 20 lb</p>")

    def test_a_finished_exercise_offers_the_whole_workout_again(self):
        self.workout.started_at = timezone.now() - timedelta(days=1)
        self.workout.save()

        response = self.client.get(self.url())

        day = self.workout.started_at.date().isoformat()
        self.assertContains(response, "Complete exercise")
        self.assertContains(
            response,
            '<button type="button" class="btn btn-success perform-complete-exercise">'
            "Complete exercise</button>",
        )
        self.assertNotContains(response, f'href="{reverse("alors:calendar")}?d={day}"')
        self.workout.refresh_from_db()
        self.assertFalse(self.workout.completed)

    def test_logging_can_be_aimed_at_one_exercise(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        other_set = WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)

        response = self.post("log", ajax=True, entry=str(other.pk))

        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["set"], other_set.pk)
        other_set.refresh_from_db()
        self.assertTrue(other_set.completed)
        # The first exercise's sets are left where they were.
        self.first.refresh_from_db()
        self.assertFalse(self.first.completed)

    def test_logging_without_a_pick_takes_the_first_set_still_to_do(self):
        other = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=2, position=1
        )
        WeightsWorkoutSet.objects.create(entry=other, reps=10, position=0)

        response = self.post("log", ajax=True, entry="")

        self.assertEqual(response.json()["set"], self.first.pk)

    def test_a_pick_of_an_exercise_that_is_not_in_the_workout_logs_nothing(self):
        response = self.post("log", ajax=True, entry="999")

        self.assertIsNone(response.json()["set"])
        self.first.refresh_from_db()
        self.assertFalse(self.first.completed)

    def test_logging_walks_through_the_sets_and_finishes_the_workout(self):
        self.post("log", ajax=True)

        response = self.post("log", ajax=True)

        self.second.refresh_from_db()
        self.assertTrue(self.second.completed)
        self.assertEqual(response.json()["done_count"], 2)
        self.assertTrue(response.json()["finished"])
        self.workout.refresh_from_db()
        self.assertTrue(self.workout.completed)

    def test_logging_with_every_set_already_done_ticks_nothing_off(self):
        WeightsWorkoutSet.objects.filter(entry__workout=self.workout).update(
            completed=True
        )

        response = self.post("log", ajax=True)

        self.assertTrue(response.json()["ok"])
        self.assertIsNone(response.json()["set"])
        self.assertEqual(response.json()["done_count"], 2)

    def test_unticking_a_set(self):
        self.first.completed = True
        self.first.save()

        self.post("undo")

        self.first.refresh_from_db()
        self.assertFalse(self.first.completed)

    def test_editing_a_set_keeps_it_ticked_off(self):
        self.first.completed = True
        self.first.save()

        response = self.post("save", ajax=True, reps="5", weight="55", rest="1:30")

        self.assertTrue(response.json()["ok"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.reps, 5)
        self.assertEqual(self.first.weight, Decimal("55.00"))
        self.assertEqual(self.first.rest_seconds, 90)
        self.assertTrue(self.first.completed)

    def test_editing_a_timed_set(self):
        entry = WeightsWorkoutExercise.objects.create(
            workout=self.workout, exercise_id=61, position=1
        )
        timed = WeightsWorkoutSet.objects.create(
            entry=entry, duration_seconds=90, position=0
        )

        response = self.post("save", model_set=timed, ajax=True, duration="1:20")

        self.assertTrue(response.json()["ok"])
        timed.refresh_from_db()
        self.assertEqual(timed.duration_seconds, 80)
        self.assertIsNone(timed.reps)

    def test_a_value_that_is_not_a_time_is_refused(self):
        response = self.post("save", ajax=True, reps="8", rest="ages")

        self.assertFalse(response.json()["ok"])
        self.assertIn("rest", response.json()["errors"])
        self.first.refresh_from_db()
        self.assertEqual(self.first.rest_seconds, 45)

    def test_removing_a_set(self):
        response = self.post("delete", ajax=True)

        self.assertEqual(response.json()["deleted"], True)
        self.assertEqual(response.json()["total_count"], 1)
        self.assertFalse(WeightsWorkoutSet.objects.filter(pk=self.first.pk).exists())

    def test_a_set_from_another_workout_is_not_found(self):
        other = WeightsWorkout.objects.create(
            created_by=self.user, title="Other", is_actual=True
        )
        entry = WeightsWorkoutExercise.objects.create(
            workout=other, exercise_id=1, position=0
        )
        model_set = WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        response = self.post("complete", model_set=model_set)

        self.assertEqual(response.status_code, 404)


class WeightsWorkoutCommentTests(TestCase):
    """Comments on an actual weights workout, from its perform page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="commenter", password="secret123"
        )
        self.client.force_login(self.user)
        self.workout = WeightsWorkout.objects.create(
            created_by=self.user, title="Leg day", is_actual=True
        )

    def url(self):
        return reverse("weights:workout_comment", args=[self.workout.pk])

    def test_adds_a_comment_to_the_actual_weights_workout(self):
        response = self.client.post(self.url(), {"text": "Felt strong"})

        self.assertRedirects(
            response,
            f"{reverse('weights:workout_perform', args=[self.workout.pk])}#comments",
        )
        comment = Comment.objects.get(weights_workout=self.workout)
        self.assertEqual(comment.text, "Felt strong")
        self.assertEqual(comment.created_by, self.user)

    def test_perform_page_shows_comments_and_the_form(self):
        Comment.objects.create(
            weights_workout=self.workout,
            text="Strong session",
            created_by=self.user,
        )

        response = self.client.get(
            reverse("weights:workout_perform", args=[self.workout.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Strong session")
        self.assertContains(response, "Add a comment")
        self.assertContains(response, self.url())

    def test_blank_comment_is_not_saved(self):
        response = self.client.post(self.url(), {"text": ""})

        self.assertRedirects(
            response,
            f"{reverse('weights:workout_perform', args=[self.workout.pk])}#comments",
        )
        self.assertFalse(Comment.objects.exists())

    def test_a_planned_weights_workout_rejects_comments(self):
        plan = WeightsWorkout.objects.create(created_by=self.user, title="Plan")

        response = self.client.post(
            reverse("weights:workout_comment", args=[plan.pk]),
            {"text": "Not allowed"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.exists())


class WorkoutCompletionTests(TestCase):
    """Starting an actual workout, and finishing it off again."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="timer", password="glute-timer"
        )
        self.client.force_login(self.user)
        self.plan = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        self.entry = WeightsWorkoutExercise.objects.create(
            workout=self.plan, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(entry=self.entry, reps=8, position=0)
        WeightsWorkoutSet.objects.create(entry=self.entry, reps=10, position=1)

    def _do(self):
        """Do the plan, returning the actual workout it starts."""
        self.client.post(reverse("weights:workout_do", args=[self.plan.pk]))
        return WeightsWorkout.objects.exclude(pk=self.plan.pk).get()

    def _perform(self, workout, action, model_set):
        return self.client.post(
            reverse("weights:workout_perform", args=[workout.pk]),
            {"set": model_set.pk, "action": action},
        )

    def _complete(self, workout):
        return self.client.post(reverse("weights:workout_complete", args=[workout.pk]))

    def _sets(self, workout):
        """A workout's own sets, in order."""
        return list(
            WeightsWorkoutSet.objects.filter(entry__workout=workout).order_by(
                "position"
            )
        )

    def _tick_everything_off(self, workout):
        """Do every set of a workout through its perform page."""
        for model_set in self._sets(workout):
            self._perform(workout, "complete", model_set)

    def _payload(self, workout):
        """POST data for a workout's edit page, with every set ticked off."""
        entry = workout.exercises.get()
        model_sets = list(entry.sets.all())
        data = {
            "title": workout.title,
            "exercises-TOTAL_FORMS": "1",
            "exercises-INITIAL_FORMS": "1",
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
            "exercises-0-id": str(entry.pk),
            "exercises-0-exercise_id": str(entry.exercise_id),
            "exercises-0-superset": "",
            "sets0-TOTAL_FORMS": str(len(model_sets)),
            "sets0-INITIAL_FORMS": str(len(model_sets)),
            "sets0-MIN_NUM_FORMS": "0",
            "sets0-MAX_NUM_FORMS": "1000",
        }
        for index, model_set in enumerate(model_sets):
            data[f"sets0-{index}-id"] = str(model_set.pk)
            data[f"sets0-{index}-reps"] = str(model_set.reps or "")
            data[f"sets0-{index}-weight"] = str(model_set.weight or "")
            data[f"sets0-{index}-duration"] = model_set.duration or ""
            data[f"sets0-{index}-rest"] = model_set.rest or ""
            data[f"sets0-{index}-completed"] = "on"
        return data

    def test_a_planned_workout_records_no_times(self):
        self.assertIsNone(self.plan.started_at)
        self.assertIsNone(self.plan.finished_at)

    def test_doing_a_plan_stamps_the_start_on_the_copy_alone(self):
        before = timezone.now()

        actual = self._do()

        self.assertIsNotNone(actual.started_at)
        self.assertGreaterEqual(actual.started_at, before)
        self.assertIsNone(actual.finished_at)
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.started_at)

    def test_a_workout_is_started_only_once(self):
        actual = self._do()
        started = actual.started_at

        self.client.get(reverse("weights:workout_perform", args=[actual.pk]))

        actual.refresh_from_db()
        self.assertEqual(actual.started_at, started)

    def test_opening_a_workout_that_was_never_started_starts_it(self):
        workout = WeightsWorkout.objects.create(
            created_by=self.user, title="By hand", is_actual=True
        )

        self.client.get(reverse("weights:workout_perform", args=[workout.pk]))

        workout.refresh_from_db()
        self.assertIsNotNone(workout.started_at)

    def test_finishing_the_last_set_stamps_the_finish(self):
        actual = self._do()
        first, second = self._sets(actual)

        self._perform(actual, "complete", first)
        actual.refresh_from_db()
        self.assertIsNone(actual.finished_at)
        self.assertFalse(actual.completed)

        before = timezone.now()
        self._perform(actual, "complete", second)

        actual.refresh_from_db()
        self.assertTrue(actual.completed)
        self.assertIsNotNone(actual.finished_at)
        self.assertGreaterEqual(actual.finished_at, before)

    def test_adding_another_set_reopens_a_finished_workout(self):
        actual = self._do()
        last = self._sets(actual)[-1]
        self._tick_everything_off(actual)
        actual.refresh_from_db()
        self.assertTrue(actual.completed)

        response = self._perform(actual, "add", last)

        self.assertEqual(response.status_code, 302)
        actual.refresh_from_db()
        self.assertFalse(actual.completed)
        self.assertIsNone(actual.finished_at)
        self.assertEqual(actual.set_count(), 3)

    def test_unticking_a_set_leaves_a_finished_workout_finished(self):
        actual = self._do()
        last = self._sets(actual)[-1]
        self._tick_everything_off(actual)
        actual.refresh_from_db()
        self.assertTrue(actual.completed)

        self._perform(actual, "undo", last)

        actual.refresh_from_db()
        self.assertTrue(actual.completed)
        self.assertIsNotNone(actual.finished_at)

    def test_ticking_the_last_set_off_on_the_edit_page_finishes_the_workout(self):
        actual = self._do()

        self.client.post(
            reverse("weights:workout_edit", args=[actual.pk]), self._payload(actual)
        )

        actual.refresh_from_db()
        self.assertTrue(actual.completed)
        self.assertIsNotNone(actual.finished_at)

    def test_the_list_marks_a_workout_that_is_done(self):
        actual = self._do()
        self._complete(actual)

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "Completed")
        self.assertNotContains(response, "Not started yet")

    def test_the_button_finishes_the_workout(self):
        actual = self._do()
        before = timezone.now()

        response = self._complete(actual)

        # Back to the calendar, on today, which is the day it was finished.
        self.assertRedirects(
            response,
            f"{reverse('alors:calendar')}?d=#today",
            fetch_redirect_response=False,
        )
        actual.refresh_from_db()
        self.assertTrue(actual.completed)
        self.assertIsNotNone(actual.finished_at)
        self.assertGreaterEqual(actual.finished_at, before)
        # A workout can be finished with sets still to do.
        self.assertEqual(actual.completed_set_count(), 0)

    def test_the_button_reopens_a_finished_workout(self):
        actual = self._do()
        self._complete(actual)

        self._complete(actual)

        actual.refresh_from_db()
        self.assertFalse(actual.completed)
        self.assertIsNone(actual.finished_at)

    def test_a_workout_finished_by_hand_stays_finished(self):
        actual = self._do()
        self._complete(actual)
        first = self._sets(actual)[0]

        self._perform(actual, "complete", first)

        actual.refresh_from_db()
        self.assertTrue(actual.completed)
        self.assertIsNotNone(actual.finished_at)

    def test_finishing_by_hand_leaves_a_plan_alone(self):
        response = self._complete(self.plan)

        self.assertRedirects(
            response,
            reverse("weights:workout_perform", args=[self.plan.pk]),
            fetch_redirect_response=False,
        )
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.completed)

    def test_finishing_requires_post(self):
        actual = self._do()

        response = self.client.get(
            reverse("weights:workout_complete", args=[actual.pk])
        )

        self.assertRedirects(
            response, reverse("weights:workout_perform", args=[actual.pk])
        )
        actual.refresh_from_db()
        self.assertFalse(actual.completed)

    def test_the_perform_page_offers_to_finish_the_workout(self):
        actual = self._do()

        response = self.client.get(reverse("weights:workout_perform", args=[actual.pk]))

        self.assertContains(response, "Complete workout")
        self.assertContains(
            response,
            f'action="{reverse("weights:workout_complete", args=[actual.pk])}"',
        )
        self.assertContains(response, "data-finish-workout")
        self.assertNotContains(response, "Reopen workout")

    def test_a_finished_workout_offers_to_be_started_again(self):
        actual = self._do()
        self._complete(actual)

        response = self.client.get(reverse("weights:workout_perform", args=[actual.pk]))

        self.assertContains(response, "Reopen workout")
        self.assertNotContains(response, "Complete workout")

    def test_the_edit_page_does_not_offer_to_finish_an_actual_workout(self):
        actual = self._do()

        response = self.client.get(reverse("weights:workout_edit", args=[actual.pk]))

        self.assertNotContains(response, "Complete workout")
        self.assertNotContains(
            response,
            f'action="{reverse("weights:workout_complete", args=[actual.pk])}"',
        )

    def test_the_edit_page_of_a_plan_offers_no_such_button(self):
        response = self.client.get(reverse("weights:workout_edit", args=[self.plan.pk]))

        self.assertNotContains(response, "Complete workout")


class WeightsWorkoutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lifter", password="secret"
        )
        self.client.force_login(self.user)

    def _data(self, exercises, title="Leg day", initial=0):
        """POST data for the exercise formset with nested sets.

        ``exercises`` is a list of ``(exercise_id, [reps, ...])``.
        """
        total = max(len(exercises), 3)
        data = {
            "title": title,
            "exercises-TOTAL_FORMS": str(total),
            "exercises-INITIAL_FORMS": str(initial),
            "exercises-MIN_NUM_FORMS": "0",
            "exercises-MAX_NUM_FORMS": "1000",
        }
        for index in range(total):
            data[f"sets{index}-TOTAL_FORMS"] = "1"
            data[f"sets{index}-INITIAL_FORMS"] = "0"
            data[f"sets{index}-MIN_NUM_FORMS"] = "0"
            data[f"sets{index}-MAX_NUM_FORMS"] = "1000"
        for index, (exercise_id, reps) in enumerate(exercises):
            data[f"exercises-{index}-exercise_id"] = str(exercise_id)
            if reps:
                data[f"sets{index}-TOTAL_FORMS"] = str(len(reps))
                for set_index, value in enumerate(reps):
                    data[f"sets{index}-{set_index}-reps"] = str(value)
        return data

    def test_list_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("weights:workout_list"))

        self.assertEqual(response.status_code, 302)

    def test_add_page_renders(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create a weights workout")
        self.assertContains(response, 'id="add-exercise-row"')
        self.assertContains(response, 'id="empty-exercise-row"')
        self.assertContains(response, "__prefix__")
        self.assertContains(response, 'name="exercises-TOTAL_FORMS"')
        self.assertContains(response, 'name="sets0-TOTAL_FORMS"')
        self.assertContains(response, 'name="sets0-0-reps"')
        self.assertContains(response, 'name="sets0-0-weight"')
        self.assertContains(response, 'name="sets0-__prefix__-reps"')
        self.assertContains(response, 'name="sets0-__prefix__-weight"')
        self.assertContains(response, 'value="8"')
        self.assertContains(response, "Back Extensions")

    def test_add_page_starts_with_one_exercise_row(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertEqual(len(response.context["groups"]), 1)
        self.assertContains(response, 'name="exercises-0-exercise_id"')
        self.assertNotContains(response, 'name="exercises-1-exercise_id"')

    def test_rows_are_removed_with_a_button_not_a_checkbox(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, "js-remove-exercise")
        self.assertContains(response, ">Remove</button>")
        # The button ticks a checkbox the formset posts, kept out of sight.
        self.assertContains(response, 'name="exercises-0-DELETE" class="d-none"')
        self.assertContains(response, 'name="sets0-0-DELETE" class="d-none"')

    def test_add_creates_workout_with_ordered_exercises_and_sets(self):
        response = self.client.post(
            reverse("weights:workout_add"), self._data([(2, [8, 6]), (1, [5])])
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        workout = WeightsWorkout.objects.get()
        self.assertEqual(workout.created_by, self.user)
        self.assertEqual(workout.title, "Leg day")
        entries = list(workout.exercises.all())
        self.assertEqual([entry.exercise_id for entry in entries], [2, 1])
        self.assertEqual([entry.position for entry in entries], [0, 1])
        self.assertEqual([s.reps for s in entries[0].sets.all()], [8, 6])
        self.assertEqual([s.reps for s in entries[1].sets.all()], [5])
        self.assertEqual([s.position for s in entries[0].sets.all()], [0, 1])

    def test_add_defaults_to_three_sets_of_eight(self):
        response = self.client.post(
            reverse("weights:workout_add"), self._data([(1, [8, 8, 8])])
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        entry = WeightsWorkout.objects.get().exercises.get()
        self.assertEqual([s.reps for s in entry.sets.all()], [8, 8, 8])

    def test_add_without_exercises_is_rejected(self):
        response = self.client.post(reverse("weights:workout_add"), self._data([]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(WeightsWorkout.objects.exists())

    def test_list_shows_exercises_and_reps(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "Back Extensions")
        self.assertContains(response, "8 reps")

    def test_edit_page_adds_one_blank_row(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        self.assertEqual(len(response.context["groups"]), 2)
        self.assertContains(response, 'name="exercises-1-exercise_id"')
        self.assertNotContains(response, 'name="exercises-2-exercise_id"')

    def test_edit_page_prefills_title_exercises_and_sets(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit weights workout")
        self.assertContains(response, "Leg day")
        self.assertContains(response, "Back Extensions")

    def test_edit_updates_title_exercises_and_sets(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Old")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        second = Exercise.choices()[1][0]

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]),
            {
                "title": "New",
                "exercises-TOTAL_FORMS": "3",
                "exercises-INITIAL_FORMS": "1",
                "exercises-MIN_NUM_FORMS": "0",
                "exercises-MAX_NUM_FORMS": "1000",
                "exercises-0-id": str(entry.pk),
                "exercises-0-exercise_id": str(second),
                "sets0-TOTAL_FORMS": "2",
                "sets0-INITIAL_FORMS": "0",
                "sets0-MIN_NUM_FORMS": "0",
                "sets0-MAX_NUM_FORMS": "1000",
                "sets0-0-reps": "10",
                "sets0-1-reps": "8",
                "sets1-TOTAL_FORMS": "1",
                "sets1-INITIAL_FORMS": "0",
                "sets1-MIN_NUM_FORMS": "0",
                "sets1-MAX_NUM_FORMS": "1000",
                "sets2-TOTAL_FORMS": "1",
                "sets2-INITIAL_FORMS": "0",
                "sets2-MIN_NUM_FORMS": "0",
                "sets2-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        workout.refresh_from_db()
        self.assertEqual(workout.title, "New")
        entries = list(workout.exercises.all())
        self.assertEqual([e.exercise_id for e in entries], [second])
        self.assertEqual([s.reps for s in entries[0].sets.all()], [10, 8])

    def test_edit_removes_a_deleted_exercise_and_renumbers(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        first = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        second = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=2, position=1
        )

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]),
            {
                "title": "Leg day",
                "exercises-TOTAL_FORMS": "3",
                "exercises-INITIAL_FORMS": "2",
                "exercises-MIN_NUM_FORMS": "0",
                "exercises-MAX_NUM_FORMS": "1000",
                "exercises-0-id": str(first.pk),
                "exercises-0-exercise_id": "1",
                "exercises-0-DELETE": "on",
                "exercises-1-id": str(second.pk),
                "exercises-1-exercise_id": "2",
                "sets0-TOTAL_FORMS": "1",
                "sets0-INITIAL_FORMS": "0",
                "sets0-MIN_NUM_FORMS": "0",
                "sets0-MAX_NUM_FORMS": "1000",
                "sets1-TOTAL_FORMS": "1",
                "sets1-INITIAL_FORMS": "0",
                "sets1-MIN_NUM_FORMS": "0",
                "sets1-MAX_NUM_FORMS": "1000",
                "sets2-TOTAL_FORMS": "1",
                "sets2-INITIAL_FORMS": "0",
                "sets2-MIN_NUM_FORMS": "0",
                "sets2-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        entries = list(workout.exercises.all())
        self.assertEqual([entry.pk for entry in entries], [second.pk])
        self.assertEqual([entry.position for entry in entries], [0])

    def test_edit_removes_a_deleted_set_and_renumbers(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        first = WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)
        second = WeightsWorkoutSet.objects.create(entry=entry, reps=6, position=1)

        response = self.client.post(
            reverse("weights:workout_edit", args=[workout.pk]),
            {
                "title": "Leg day",
                "exercises-TOTAL_FORMS": "3",
                "exercises-INITIAL_FORMS": "1",
                "exercises-MIN_NUM_FORMS": "0",
                "exercises-MAX_NUM_FORMS": "1000",
                "exercises-0-id": str(entry.pk),
                "exercises-0-exercise_id": "1",
                "sets0-TOTAL_FORMS": "2",
                "sets0-INITIAL_FORMS": "2",
                "sets0-MIN_NUM_FORMS": "0",
                "sets0-MAX_NUM_FORMS": "1000",
                "sets0-0-id": str(first.pk),
                "sets0-0-reps": "8",
                "sets0-0-DELETE": "on",
                "sets0-1-id": str(second.pk),
                "sets0-1-reps": "6",
                "sets1-TOTAL_FORMS": "1",
                "sets1-INITIAL_FORMS": "0",
                "sets1-MIN_NUM_FORMS": "0",
                "sets1-MAX_NUM_FORMS": "1000",
                "sets2-TOTAL_FORMS": "1",
                "sets2-INITIAL_FORMS": "0",
                "sets2-MIN_NUM_FORMS": "0",
                "sets2-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        sets = list(entry.sets.all())
        self.assertEqual([s.pk for s in sets], [second.pk])
        self.assertEqual([s.position for s in sets], [0])

    def test_delete_removes_workout_exercises_and_sets(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        response = self.client.post(
            reverse("weights:workout_delete", args=[workout.pk])
        )

        self.assertRedirects(response, reverse("weights:workout_list"))
        self.assertFalse(WeightsWorkout.objects.exists())
        self.assertFalse(WeightsWorkoutExercise.objects.exists())
        self.assertFalse(WeightsWorkoutSet.objects.exists())

    def test_delete_requires_post(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")

        response = self.client.get(reverse("weights:workout_delete", args=[workout.pk]))

        self.assertRedirects(response, reverse("weights:workout_list"))
        self.assertTrue(WeightsWorkout.objects.filter(pk=workout.pk).exists())

    def test_delete_of_a_started_workout_returns_to_its_day_on_the_calendar(self):
        workout = WeightsWorkout.objects.create(
            created_by=self.user, title="Leg day", is_actual=True
        )
        workout.mark_started()

        response = self.client.post(
            reverse("weights:workout_delete", args=[workout.pk])
        )

        day = workout.started_at.date().isoformat()
        self.assertEqual(response.url, f"/calendar/?d={day}#date-{day}")
        self.assertFalse(WeightsWorkout.objects.exists())

    def test_duplicate_copies_the_whole_workout(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        first = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(
            entry=first, reps=8, weight=Decimal("50.5"), position=0
        )
        WeightsWorkoutSet.objects.create(entry=first, reps=6, position=1)
        second = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=61, position=1
        )
        WeightsWorkoutSet.objects.create(
            entry=second, duration_seconds=90, weight=Decimal("10"), position=0
        )

        response = self.client.post(
            reverse("weights:workout_duplicate", args=[workout.pk])
        )

        duplicate = WeightsWorkout.objects.exclude(pk=workout.pk).get()
        self.assertRedirects(
            response, reverse("weights:workout_edit", args=[duplicate.pk])
        )
        self.assertEqual(duplicate.title, "Leg day")
        self.assertEqual(duplicate.created_by, self.user)
        entries = list(duplicate.exercises.all())
        self.assertEqual([entry.exercise_id for entry in entries], [1, 61])
        self.assertEqual([entry.position for entry in entries], [0, 1])
        first_sets = list(entries[0].sets.all())
        self.assertEqual([model_set.reps for model_set in first_sets], [8, 6])
        self.assertEqual(
            [model_set.weight for model_set in first_sets], [Decimal("50.5"), None]
        )
        self.assertEqual([model_set.position for model_set in first_sets], [0, 1])
        timed_set = entries[1].sets.get()
        self.assertEqual(timed_set.duration_seconds, 90)
        self.assertEqual(timed_set.weight, Decimal("10"))
        self.assertIsNone(timed_set.reps)

    def test_duplicate_leaves_the_original_alone(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(entry=entry, reps=8, position=0)

        self.client.post(reverse("weights:workout_duplicate", args=[workout.pk]))

        self.assertEqual(WeightsWorkout.objects.count(), 2)
        self.assertEqual(workout.exercises.count(), 1)
        self.assertEqual(workout.exercises.get().sets.count(), 1)

    def test_duplicate_keeps_the_title_as_it_is(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="")

        self.client.post(reverse("weights:workout_duplicate", args=[workout.pk]))

        self.assertEqual(WeightsWorkout.objects.exclude(pk=workout.pk).get().title, "")

    def test_duplicate_requires_post(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")

        response = self.client.get(
            reverse("weights:workout_duplicate", args=[workout.pk])
        )

        self.assertRedirects(
            response, reverse("weights:workout_edit", args=[workout.pk])
        )
        self.assertEqual(WeightsWorkout.objects.count(), 1)

    def test_edit_page_offers_a_duplicate_button(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")

        response = self.client.get(reverse("weights:workout_edit", args=[workout.pk]))

        self.assertContains(response, "Duplicate workout")
        self.assertContains(
            response,
            f'action="{reverse("weights:workout_duplicate", args=[workout.pk])}"',
        )

    def test_add_page_has_no_duplicate_button(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertNotContains(response, "Duplicate workout")

    def test_add_saves_a_weight_per_set(self):
        data = self._data([(1, [8, 8])])
        data["sets0-0-weight"] = "50.5"
        data["sets0-1-weight"] = "52.5"

        response = self.client.post(reverse("weights:workout_add"), data)

        self.assertRedirects(response, reverse("weights:workout_list"))
        entry = WeightsWorkout.objects.get().exercises.get()
        self.assertEqual(
            [model_set.weight for model_set in entry.sets.all()],
            [Decimal("50.5"), Decimal("52.5")],
        )

    def test_add_page_labels_weight_with_the_profile_units(self):
        UserProfile.objects.create(user=self.user, units="metric")

        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, '<span class="text-muted small">kg</span>')
        self.assertNotContains(response, '<span class="text-muted small">lb</span>')

    def test_add_page_falls_back_to_imperial_units(self):
        response = self.client.get(reverse("weights:workout_add"))

        self.assertContains(response, '<span class="text-muted small">lb</span>')

    def test_list_shows_set_weights_with_the_profile_units(self):
        workout = WeightsWorkout.objects.create(created_by=self.user, title="Leg day")
        entry = WeightsWorkoutExercise.objects.create(
            workout=workout, exercise_id=1, position=0
        )
        WeightsWorkoutSet.objects.create(
            entry=entry, reps=8, weight=Decimal("50"), position=0
        )
        UserProfile.objects.create(user=self.user, units="metric")

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "8 reps @ 50.00 kg")


class WeightsVisibilityTests(TestCase):
    """Weights workouts follow the same sharing rules as the calendar."""

    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username="viewer", password="secret")
        self.owner = User.objects.create_user(username="owner", password="secret")
        self.stranger = User.objects.create_user(username="stranger", password="secret")
        UserProfile.objects.create(user=self.viewer)
        owner_profile = UserProfile.objects.create(user=self.owner)
        UserProfile.objects.create(user=self.stranger)
        owner_profile.visibility.add(self.viewer)
        self.client.force_login(self.viewer)

        self.viewer_plan = WeightsWorkout.objects.create(
            created_by=self.viewer, title="Viewer plan"
        )
        self.owner_plan = WeightsWorkout.objects.create(
            created_by=self.owner, title="Owner plan"
        )
        self.stranger_plan = WeightsWorkout.objects.create(
            created_by=self.stranger, title="Stranger plan"
        )
        self.owner_actual = WeightsWorkout.objects.create(
            created_by=self.owner, title="Owner actual", is_actual=True
        )

    def test_list_shows_own_and_shared_plans_only(self):
        response = self.client.get(reverse("weights:workout_list"))

        content = response.content.decode().lower()
        self.assertIn("viewer plan", content)
        self.assertIn("owner plan", content)
        self.assertNotIn("stranger plan", content)
        self.assertNotIn("owner actual", content)

    def test_can_edit_a_shared_workout_but_not_an_unshared_one(self):
        response = self.client.get(
            reverse("weights:workout_edit", args=[self.owner_plan.pk])
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("weights:workout_edit", args=[self.stranger_plan.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_can_perform_a_shared_workout_but_not_an_unshared_one(self):
        response = self.client.get(
            reverse("weights:workout_perform", args=[self.owner_actual.pk])
        )
        self.assertEqual(response.status_code, 200)

        stranger_actual = WeightsWorkout.objects.create(
            created_by=self.stranger, title="Stranger actual", is_actual=True
        )
        response = self.client.get(
            reverse("weights:workout_perform", args=[stranger_actual.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_can_delete_a_shared_workout_but_not_an_unshared_one(self):
        response = self.client.post(
            reverse("weights:workout_delete", args=[self.owner_plan.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(WeightsWorkout.objects.filter(pk=self.owner_plan.pk).exists())

        response = self.client.post(
            reverse("weights:workout_delete", args=[self.stranger_plan.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            WeightsWorkout.objects.filter(pk=self.stranger_plan.pk).exists()
        )
