from django.contrib import admin

from .models import Exercise


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "level",
        "force",
        "mechanic",
        "equipment",
    )
    list_filter = ("category", "level", "force", "mechanic", "equipment")
    search_fields = ("name",)
