from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from .forms import PlannedWorkoutForm, WarmUpForm
from .models import PlannedWorkout, WarmUp
from django.utils import timezone
from .utils import daily, weekly, monthly
from .validators import validate_date
from .ical import render_calendar

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
    view = request.GET.get('v', None)
    view = view if view else 'weekly'
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

    workouts_by_date = {}
    for workout in workouts:
        date = workout.workout_date.strftime('%Y-%m-%d')
        if date not in workouts_by_date:
            workouts_by_date[date] = []
        workouts_by_date[date].append(workout)

    days = []
    totals = {}
    for i in range((dates['end'] - dates['start']).days + 1):
        day = dates['start'] + timezone.timedelta(days=i)
        key = day.strftime('%Y-%m-%d')
        days.append({'date': day, 'workouts': workouts_by_date.get(key, None)})

        if day.weekday() == 6:  # Sunday
            days[-1]['totals'] = totals.copy()
            totals.clear()
        else:
            if "workout_count" not in totals:
                totals["workout_count"] = 0
            if "workout_distance" not in totals:
                totals["workout_distance"] = 0
            workouts = workouts_by_date.get(key, [])
            totals["workout_count"] += len(workouts)
            totals["workout_distance"] += sum(w.total_distance for w in workouts_by_date.get(key, []))

    return render(request, 'calendar.html', {'date': date, 'next': dates['next'], 'previous': dates['previous'], 'days': days })

@login_required
def add_planned_workout(request):
    if request.method == 'POST':
        form = PlannedWorkoutForm(request.POST)
        if form.is_valid():
            workout = form.save(commit=False)
            workout.created_by = request.user
            workout.save()
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


def planned_workout_webcal(request):
    """Return every planned workout as an iCalendar (.ics) document.

    The document can be downloaded and imported, or the URL subscribed to
    via the ``webcal://`` scheme in most calendar applications.
    """
    workouts = PlannedWorkout.objects.all().order_by('workout_date')
    payload = render_calendar(workouts, base_url=request.build_absolute_uri('/'))
    response = HttpResponse(payload, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="planned-workouts.ics"'
    return response


@login_required
def warmup_list(request):
    warmups = WarmUp.objects.all().order_by('title')
    return render(request, 'warmup_list.html', {'warmups': warmups})


@login_required
def warmup_add(request):
    if request.method == 'POST':
        form = WarmUpForm(request.POST)
        if form.is_valid():
            warmup = form.save(commit=False)
            warmup.created_by = request.user
            warmup.save()
            messages.add_message(
                request, messages.SUCCESS,
                f'🎉 Added warm-up "{warmup.title}".',
            )
            return redirect('alors:warmup_list')
    else:
        form = WarmUpForm()

    return render(request, 'warmup_form.html', {
        'form': form,
        'page_title': 'Add a warm-up',
        'page_intro': 'Write a warm-up routine you can reuse.',
    })


@login_required
def warmup_edit(request, pk):
    warmup = get_object_or_404(WarmUp, pk=pk)
    if request.method == 'POST':
        form = WarmUpForm(request.POST, instance=warmup)
        if form.is_valid():
            form.save()
            messages.add_message(
                request, messages.SUCCESS,
                f'✏️ Updated warm-up "{warmup.title}".',
            )
            return redirect('alors:warmup_list')
    else:
        form = WarmUpForm(instance=warmup)

    return render(request, 'warmup_form.html', {
        'form': form,
        'warmup': warmup,
        'page_title': 'Edit warm-up',
        'page_intro': f'Update your "{warmup.title}" warm-up.',
    })


@login_required
def warmup_delete(request, pk):
    warmup = get_object_or_404(WarmUp, pk=pk)
    if request.method == 'POST':
        title = warmup.title
        warmup.delete()
        messages.add_message(
            request, messages.SUCCESS,
            f'🗑️ Deleted warm-up "{title}".',
        )
    return redirect('alors:warmup_list')    