from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ..models import (
    PlannedWorkout,
    WarmUp,
    WeeklySummary,
    Workout,
    WorkoutType,
)


class AddPlannedWorkoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="secret123")
        self.client.force_login(self.user)
        self.warmup = WarmUp.objects.create(
            title="Easy jog",
            text="Jog slowly.",
            created_by=self.user,
        )

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

    def test_add_can_link_a_warmup_instance(self):
        response = self.client.post(
            reverse("alors:add_planned"),
            {
                "title": "Long run",
                "workout_type": WorkoutType.RUN,
                "workout_date": "2026-09-05",
                "total_distance": "21.10",
                "warm_up": self.warmup.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        workout = PlannedWorkout.objects.get()
        self.assertEqual(workout.warm_up, self.warmup)

    def test_warm_up_field_is_optional_with_empty_label(self):
        from ..forms import PlannedWorkoutForm

        field = PlannedWorkoutForm().fields["warm_up"]
        self.assertFalse(field.required)
        self.assertEqual(field.empty_label, "No warm-up")

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
        self.assertEqual(self.user.planned_workouts.count(), 1)
        self.assertEqual(
            self.user.planned_workouts.get().title,
            "Long run",
        )

    def test_add_page_shows_weekly_summary_for_provided_date(self):
        # Saving the workout creates a WeeklySummary for its week (09-06).
        self.add_workout()
        response = self.client.get(reverse("alors:add_planned"), {"date": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Summary")
        self.assertContains(response, "workout for")
        self.assertContains(response, "21.1 km")

    def test_add_page_shows_placeholder_when_week_has_no_summary(self):
        response = self.client.get(reverse("alors:add_planned"), {"date": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No weekly summary for this date yet.")

    def test_weekly_summary_snippet_returns_summary_for_date(self):
        self.add_workout()
        response = self.client.get(
            reverse("alors:planned_weekly_summary"), {"date": "2026-09-05"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "workout for")
        self.assertContains(response, "21.1 km")

    def test_weekly_summary_snippet_returns_placeholder_without_data(self):
        response = self.client.get(
            reverse("alors:planned_weekly_summary"), {"date": "2026-09-05"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No plan yet.")


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
    def create_planned(self, workout_date, distance="10.00", workout_type="run"):
        return PlannedWorkout.objects.create(
            workout_type=workout_type,
            workout_date=workout_date,
            total_distance=distance,
        )

    def create_workout_record(self, workout_date, distance="10.00", workout_type="run"):
        if isinstance(workout_date, date) and not isinstance(workout_date, datetime):
            workout_date = datetime.combine(workout_date, datetime.min.time())
        return Workout.objects.create(
            workout_date=workout_date,
            total_time=timedelta(minutes=30),
            workout_type=workout_type,
            total_distance=distance,
        )

    def summary_for(self, sunday):
        return WeeklySummary.objects.get(date=sunday)

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
            },
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

    def test_non_run_workout_does_not_update_weekly_summary(self):
        self.create_workout_record(date(2026, 9, 2), workout_type="walk")
        self.assertFalse(WeeklySummary.objects.filter(date=date(2026, 9, 6)).exists())

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
        first = self.create_planned()
        second = self.create_planned(title="Second run")
        self.create_workout(total_distance=Decimal("10.00"))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "")
        self.assertEqual(second.status, "")


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
