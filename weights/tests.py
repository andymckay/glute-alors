import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from alors.models import UserProfile

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

    def test_timed_ids_lists_every_timed_exercise(self):
        timed_ids = Exercise.timed_ids()

        self.assertIn(61, timed_ids)
        self.assertNotIn(1, timed_ids)
        self.assertEqual(len(timed_ids), 134)

    def test_returned_json_is_independent_of_the_cached_source(self):
        Exercise.get_exercises()[0]["relationships"]["equipment"]["data"].clear()

        self.assertTrue(Exercise.get_exercises()[0]["relationships"]["equipment"]["data"])

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

        response = self.client.get(
            reverse("weights:workout_edit", args=[workout.pk])
        )

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
        response = self.client.get(
            reverse("weights:exercise_detail", args=[999999])
        )

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
                        for name, value in (sets or {}).get(
                            (index, set_index), {}
                        ).items()
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

        response = self.client.get(
            reverse("weights:workout_edit", args=[actual.pk])
        )

        self.assertContains(response, 'name="sets0-0-completed"')
        self.assertContains(response, 'name="sets0-__prefix__-completed"')
        self.assertContains(response, "0 of 3 sets done")
        self.assertNotContains(response, "Do workout")

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

    def test_plan_page_offers_to_start_the_workout(self):
        plan = self._plan()

        response = self.client.get(reverse("weights:workout_edit", args=[plan.pk]))

        self.assertContains(response, "Do workout")
        self.assertContains(
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

    def test_list_shows_the_actual_workout_and_its_progress(self):
        plan = self._plan()
        actual = self._do(plan)
        first = actual.exercises.first().sets.first()
        first.completed = True
        first.save()

        response = self.client.get(reverse("weights:workout_list"))

        self.assertContains(response, "Actual")
        self.assertContains(response, "1 of 3 sets done")
        self.assertContains(response, plan.title)
        self.assertNotContains(response, f"weights/{actual.pk}/do/")

    def test_a_set_can_be_ticked_off_and_removed_from_an_actual_workout(self):
        actual = self._do(self._plan())

        response = self.client.get(reverse("weights:workout_edit", args=[actual.pk]))

        self.assertContains(response, 'name="sets0-0-completed" class="form-check-input"')
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
        self.assertEqual([step.rest_seconds for step in steps], [None, 90, None, 90, 90])
        self.assertEqual(steps[1].rest, "1:30")
        self.assertEqual(steps[1].superset, group)

    def test_sets_with_nothing_to_do_are_left_out(self):
        self._entry(1, 0, [{"reps": None}, {"reps": 8}])

        steps = self.workout.steps()

        self.assertEqual([step.set.reps for step in steps], [8])
        self.assertEqual(steps[0].number, 2)

    def test_timed_sets_are_marked_as_timed(self):
        self._entry(61, 0, [{"duration_seconds": 90}])

        step = self.workout.steps()[0]

        self.assertTrue(step.timed)
        self.assertIsNone(step.rest_seconds)

    def test_a_step_knows_when_it_is_done(self):
        self._entry(1, 0, [{"reps": 8, "completed": True}])

        self.assertTrue(self.workout.steps()[0].done)

    def test_repr_names_the_step(self):
        entry = self._entry(1, 0, [{"reps": 8}])

        self.assertEqual(repr(self.workout.steps()[0]), f"<WorkoutStep {entry} set 1 of 1>")


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
        self.assertEqual((response.context["done_count"], response.context["total_count"]), (0, 2))
        self.assertContains(response, "Leg day")
        self.assertContains(response, "set 1 of 2")
        self.assertContains(response, "8 reps")
        self.assertContains(response, "of 2 sets")
        self.assertContains(response, 'style="width: 0%"')

    def test_it_opens_on_the_first_set_still_to_do(self):
        self.first.completed = True
        self.first.save()

        response = self.client.get(self.url())

        self.assertEqual(response.context["current_index"], 1)
        self.assertEqual(response.context["done_count"], 1)

    def test_a_superset_step_names_its_round(self):
        group = WeightsWorkoutSuperset.objects.create(
            workout=self.workout, letter="A", rest_seconds=90
        )
        self.entry.superset = group
        self.entry.save()
        self.second.superset = group
        self.second.save()

        response = self.client.get(self.url())

        self.assertContains(response, "Superset A &middot; round 1 of 2")
        self.assertContains(response, "rest 1:30")

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
                "done_count": 1,
                "total_count": 2,
                "errors": {},
            },
        )
        self.first.refresh_from_db()
        self.assertTrue(self.first.completed)

    def test_unticking_a_set(self):
        self.first.completed = True
        self.first.save()

        self.post("undo")

        self.first.refresh_from_db()
        self.assertFalse(self.first.completed)

    def test_editing_a_set_keeps_it_ticked_off(self):
        self.first.completed = True
        self.first.save()

        response = self.post(
            "save", ajax=True, reps="5", weight="55", rest="1:30"
        )

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
        self.assertContains(response, "id=\"add-exercise-row\"")
        self.assertContains(response, "id=\"empty-exercise-row\"")
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

        self.assertEqual(
            WeightsWorkout.objects.exclude(pk=workout.pk).get().title, ""
        )

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
