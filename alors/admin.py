from django.contrib import admin

from .models import Issue, PlannedWorkout, WarmUp, WeeklySummary, Workout


@admin.register(PlannedWorkout)
class PlannedWorkoutAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "workout_type",
        "workout_date",
        "total_distance",
        "warm_up",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("workout_type", "workout_date", "created_by")
    search_fields = ("title", "notes")
    date_hierarchy = "workout_date"


@admin.register(WarmUp)
class WarmUpAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "created_at", "updated_at")
    list_filter = ("created_by",)
    search_fields = ("title", "text")


@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = (
        "workout_date",
        "workout_type",
        "total_time",
        "total_distance",
        "moving_time",
        "average_speed",
        "effort",
        "feeling",
    )
    list_filter = ("workout_type", "workout_date")
    search_fields = ("notes",)
    date_hierarchy = "workout_date"


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "created_at", "updated_at")
    list_filter = ("created_by",)
    search_fields = ("title", "text")


@admin.register(WeeklySummary)
class WeeklySummaryAdmin(admin.ModelAdmin):
    list_display = ("date", "summary")
    date_hierarchy = "date"
