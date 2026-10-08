from django.contrib import admin

from .models import Health


@admin.register(Health)
class HealthAdmin(admin.ModelAdmin):
    list_display = (
        "created_by",
        "weight",
        "blood_pressure",
        "resting_heart_rate",
        "created_at",
    )
    list_filter = ("created_by",)
    search_fields = ("created_by__username", "created_by__email")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
