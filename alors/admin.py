from django.contrib import admin

from .models import PlannedWorkout, WarmUp


@admin.register(PlannedWorkout)
class PlannedWorkoutAdmin(admin.ModelAdmin):
    list_display = ("title", "workout_type", "workout_date", "total_distance", "warm_up", "created_by", "created_at", "updated_at")
    list_filter = ("workout_type", "workout_date", "created_by")
    search_fields = ("title", "notes")
    date_hierarchy = "workout_date"


@admin.register(WarmUp)
class WarmUpAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "created_at", "updated_at")
    list_filter = ("created_by",)
    search_fields = ("title", "text")
