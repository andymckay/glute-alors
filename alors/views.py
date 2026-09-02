from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from .forms import PlannedWorkoutForm
from .models import PlannedWorkout
from django.utils import timezone
from .utils import daily, weekly, monthly
from .validators import validate_date

def index(request):
    if request.user.is_authenticated:
        return redirect('alors:calendar')
    return render(request, 'index.html')

def login(request):
    next_url = request.GET.get('next', '') or request.POST.get('next', '') or ''
    if not next_url.startswith('/'):
        next_url = ''

    if request.method == 'POST':
        user = auth.authenticate(request, username=request.POST.get('username', ''), password=request.POST.get('password'))
        if user is not None:
            auth.login(request, user)
            return redirect(next_url or 'alors:index')
        else:
            messages.add_message(request, messages.ERROR, '🤔 Wrong username or password.')
            return render(request, 'index.html', {'next': next_url})

    return render(request, 'index.html', {'next': next_url})

@login_required
def logout(request):
    auth.logout(request)
    return redirect('alors:index')

@login_required
def calendar(request):
    date = request.GET.get('d', None)
    date = date if date else timezone.now().strftime('%Y-%m-%d')
    view = request.GET.get('v', 'weekly')
    try:
        validate_date(date)
    except ValidationError:
        messages.add_message(request, messages.ERROR, f'🤔 {date} is not a valid date.')
        return redirect('alors:calendar')

    if view == 'daily':
        dates = daily(date)
    elif view == 'weekly':
        dates = weekly(date)
    elif view == 'monthly':
        dates = monthly(date)
    else:
        messages.add_message(request, messages.ERROR, f'🤔 {view} is not a valid calendar view.')
        return redirect('alors:calendar')
    
    workouts = PlannedWorkout.objects.filter(workout_date__gte=dates['start'], workout_date__lte=dates['end']).order_by('workout_date')
    return render(request, 'calendar.html', {'date': date, 'workouts': workouts, 'next': dates['next'], 'previous': dates['previous'] })

@login_required
def add_planned_workout(request):
    if request.method == 'POST':
        form = PlannedWorkoutForm(request.POST)
        if form.is_valid():
            workout = form.save()
            messages.add_message(
                request, messages.SUCCESS,
                f'🎉 Planned {workout.get_workout_type_display().lower()} added for {workout.workout_date}.',
            )
            return redirect('alors:index')
    else:
        form = PlannedWorkoutForm()

    return render(request, 'planned.html', {'form': form})

@login_required
def edit_planned_workout(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    if request.method == 'POST':
        form = PlannedWorkoutForm(request.POST, instance=workout)
        if form.is_valid():
            workout = form.save()
            messages.add_message(
                request, messages.SUCCESS,
                f'✏️ Updated {workout.get_workout_type_display().lower()} workout for {workout.workout_date}.',
            )
            return redirect('alors:index')
    else:
        form = PlannedWorkoutForm(instance=workout)

    return render(request, 'planned.html', {
        'form': form,
        'workout': workout,
        'page_title': 'Edit workout',
        'page_intro': f'Update your planned {workout.get_workout_type_display().lower()} workout for {workout.workout_date}.',
    })

@login_required
def delete_planned_workout(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    if request.method == 'POST':
        label = workout.get_workout_type_display().lower()
        workout_date = workout.workout_date
        workout.delete()
        messages.add_message(
            request, messages.SUCCESS,
            f'🗑️ Deleted {label} workout for {workout_date}.',
        )
    return redirect('alors:index')


@login_required
def planned_workout_detail(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    return render(request, 'detail.html', {'workout': workout})    