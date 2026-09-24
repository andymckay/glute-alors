from django.contrib import admin

from .models import Exercise


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "level",
        "mobility_type",
        "is_bodyweight",
        "is_cardio",
        "rating",
    )
    list_filter = (
        "level",
        "mobility_type",
        "is_bodyweight",
        "is_cardio",
        "is_timed",
        "is_distance",
        "is_web_published",
        "rating",
    )
    search_fields = ("name", "alias", "slug")
    readonly_fields = ("raw", "imported_at")
