from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    path("", views.health_list, name="health_list"),
    path("add/", views.health_add, name="health_add"),
    path("<int:pk>/edit/", views.health_edit, name="health_edit"),
    path("<int:pk>/delete/", views.health_delete, name="health_delete"),
]
