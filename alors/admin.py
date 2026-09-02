from django.contrib import admin

from .models import PlannedWorkout


@admin.register(PlannedWorkout)
class PlannedWorkoutAdmin(admin.ModelAdmin):
    list_display = ("workout_type", "workout_date", "total_distance", "created_at", "updated_at")
    list_filter = ("workout_type", "workout_date")
    search_fields = ("notes", "warm_up")
    date_hierarchy = "workout_date"
