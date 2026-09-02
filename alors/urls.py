from django.urls import path

from . import views

app_name = "alors"
urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('calendar/', views.calendar, name='calendar'),
    path('workouts/add/', views.add_planned_workout, name='add_planned_workout'),
    path('workouts/<int:pk>/', views.planned_workout_detail, name='planned_workout_detail'),
    path('workouts/<int:pk>/edit/', views.edit_planned_workout, name='edit_planned_workout'),
    path('workouts/<int:pk>/delete/', views.delete_planned_workout, name='delete_planned_workout'),
    path('workouts/webcal.ics', views.planned_workout_webcal, name='planned_workout_webcal'),
    path('warmups/', views.warmup_list, name='warmup_list'),
    path('warmups/add/', views.warmup_add, name='warmup_add'),
    path('warmups/<int:pk>/edit/', views.warmup_edit, name='warmup_edit'),
    path('warmups/<int:pk>/delete/', views.warmup_delete, name='warmup_delete'),
]