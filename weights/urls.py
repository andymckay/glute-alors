from django.urls import path

from . import views

app_name = "weights"

urlpatterns = [
    path("", views.workout_list, name="workout_list"),
    path("add/", views.workout_add, name="workout_add"),
    path("<int:pk>/edit/", views.workout_edit, name="workout_edit"),
    path("<int:pk>/do/", views.workout_do, name="workout_do"),
    path("<int:pk>/duplicate/", views.workout_duplicate, name="workout_duplicate"),
    path("<int:pk>/delete/", views.workout_delete, name="workout_delete"),
]
