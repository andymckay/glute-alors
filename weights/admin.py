from django.contrib import admin

from .models import WeightsWorkout, WeightsWorkoutExercise


class WeightsWorkoutExerciseInline(admin.TabularInline):
    model = WeightsWorkoutExercise
    extra = 1


@admin.register(WeightsWorkout)
class WeightsWorkoutAdmin(admin.ModelAdmin):
    list_display = ("created_by", "is_actual", "created_at", "updated_at")
    list_filter = ("created_by", "is_actual")
    search_fields = ("created_by__username", "created_by__email")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [WeightsWorkoutExerciseInline]
