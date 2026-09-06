from django.contrib import admin

from .models import (
    Comment,
    Issue,
    Label,
    Notification,
    PlannedWorkout,
    UserProfile,
    WarmUp,
    WeeklySummary,
    Workout,
)


@admin.register(PlannedWorkout)
class PlannedWorkoutAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "workout_type",
        "is_race",
        "workout_date",
        "total_distance",
        "status",
        "warm_up",
        "comment_count",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("workout_type", "is_race", "status", "workout_date", "created_by")
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
        "effort",
        "feeling",
        "comment_count",
        "created_by",
    )
    list_filter = ("workout_type", "workout_date", "created_by")
    search_fields = ("notes",)
    date_hierarchy = "workout_date"


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "colour",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("colour", "created_by")
    search_fields = ("title",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        "text",
        "planned_workout",
        "workout",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("created_by", "planned_workout", "workout")
    search_fields = ("text",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "actor",
        "recipient",
        "content_type",
        "object_id",
        "read",
        "created_at",
    )
    list_filter = ("action", "actor", "recipient", "read", "content_type")
    search_fields = ("object_id",)
    date_hierarchy = "created_at"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at", "updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")


@admin.register(WeeklySummary)
class WeeklySummaryAdmin(admin.ModelAdmin):
    list_display = ("date", "summary")
    date_hierarchy = "date"


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "colour",
        "start_date",
        "end_date",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("colour", "created_by")
    search_fields = ("title",)
    date_hierarchy = "start_date"
