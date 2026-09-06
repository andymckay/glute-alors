from django.urls import path

from . import views

app_name = "alors"
urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("profile/", views.edit_profile, name="profile"),
    path("notifications/", views.notifications, name="notifications"),
    path(
        "notifications/mark-all-read/",
        views.mark_all_notifications_read,
        name="mark_all_notifications_read",
    ),
    path("calendar/", views.calendar, name="calendar"),
    path("planned/add/", views.add_planned, name="add_planned"),
    path(
        "planned/week-summary/",
        views.planned_weekly_summary,
        name="planned_weekly_summary",
    ),
    path(
        "planned/<int:pk>/",
        views.planned_detail,
        name="planned_detail",
    ),
    path(
        "planned/<int:pk>/edit/",
        views.edit_planned,
        name="edit_planned",
    ),
    path(
        "planned/<int:pk>/delete/",
        views.delete_planned,
        name="delete_planned",
    ),
    path(
        "planned/webcal.ics",
        views.planned_webcal,
        name="planned_webcal",
    ),
    path("workout/<int:pk>/", views.workout_detail, name="workout_detail"),
    path("workout/<int:pk>/edit/", views.workout_edit, name="workout_edit"),
    path(
        "workout/<int:pk>/comment/",
        views.add_workout_comment,
        name="add_workout_comment",
    ),
    path(
        "planned/<int:pk>/comment/",
        views.add_planned_comment,
        name="add_planned_comment",
    ),
    path("warmups/", views.warmup_list, name="warmup_list"),
    path("warmups/add/", views.warmup_add, name="warmup_add"),
    path("warmups/<int:pk>/edit/", views.warmup_edit, name="warmup_edit"),
    path("warmups/<int:pk>/delete/", views.warmup_delete, name="warmup_delete"),
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/add/", views.issue_add, name="issue_add"),
    path("issues/<int:pk>/edit/", views.issue_edit, name="issue_edit"),
    path("issues/<int:pk>/delete/", views.issue_delete, name="issue_delete"),
    path("labels/", views.label_list, name="label_list"),
    path("labels/add/", views.label_add, name="label_add"),
    path("labels/<int:pk>/edit/", views.label_edit, name="label_edit"),
    path("labels/<int:pk>/delete/", views.label_delete, name="label_delete"),
    path("debug/styles", views.styles),
]
