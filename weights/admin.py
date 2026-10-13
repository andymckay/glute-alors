from django.contrib import admin

from .models import WeightsWorkout, WeightsWorkoutExercise


class WeightsWorkoutExerciseInline(admin.TabularInline):
    model = WeightsWorkoutExercise
    extra = 1


@admin.register(WeightsWorkout)
class WeightsWorkoutAdmin(admin.ModelAdmin):
    list_display = (
        "created_by",
        "is_actual",
        "completed",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    )
    list_filter = ("created_by", "is_actual", "completed")
    search_fields = ("created_by__username", "created_by__email")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    date_hierarchy = "created_at"
    inlines = [WeightsWorkoutExerciseInline]
