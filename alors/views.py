from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from .forms import (
    CalendarForm,
    CommentForm,
    IssueForm,
    LabelForm,
    PlannedWorkoutForm,
    ProfileForm,
    WarmUpForm,
    WorkoutEditForm,
)
from .models import (
    Notification,
    Workout,
    PlannedWorkout,
    WarmUp,
    Issue,
    Label,
    UserProfile,
    WeeklySummary,
)
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import timedelta

from .validators import validate_date
from .ical import render_calendar
from itertools import chain
from .utils import dateList, combineDateLists
import json


def index(request):
    if request.user.is_authenticated:
        return redirect("alors:calendar")
    return render(request, "index.html")


def login(request):
    next_url = request.GET.get("next", "") or request.POST.get("next", "") or ""
    if not next_url.startswith("/"):
        next_url = ""

    if request.method == "POST":
        user = auth.authenticate(
            request,
            username=request.POST.get("username", ""),
            password=request.POST.get("password"),
        )
        if user is not None:
            auth.login(request, user)
            return redirect(next_url or "alors:index")
        else:
            messages.add_message(
                request, messages.ERROR, "🤔 Wrong username or password."
            )
            return render(request, "index.html", {"next": next_url})

    return render(request, "index.html", {"next": next_url})


@login_required
def logout(request):
    auth.logout(request)
    return redirect("alors:index")


@login_required
def calendar(request):
    form = CalendarForm(request.GET)
    form.is_valid()
    date = form.cleaned_data["d"]
    dates = form.cleaned_data["start_end_dates"]
    list_dates = form.cleaned_data["list_dates"]

    planned_workouts = dateList(
        PlannedWorkout.objects.filter(
            workout_date__gte=dates["start"], workout_date__lte=dates["end"]
        ).order_by("workout_date")
    )

    actual_workouts = dateList(
        Workout.objects.filter(
            workout_date__gte=dates["start"], workout_date__lte=dates["end"]
        ).order_by("workout_date")
    )

    summaries = dateList(
        WeeklySummary.objects.filter(
            date__gte=dates["start"], date__lte=dates["end"]
        ).order_by("date")
    )

    labels = dateList(
        Label.objects.filter(
            start_date__lte=dates["end"],
            end_date__gte=dates["start"],
        ).order_by("title")
    )

    results = combineDateLists(
        list_dates,
        planned=planned_workouts,
        actual=actual_workouts,
        summaries=summaries,
        labels=labels,
    )
    return render(
        request,
        "calendar.html",
        {
            "today": dates["today"],
            "date": date,
            "next": dates["next"],
            "previous": dates["previous"],
            "dates_and_objects": results,
        },
    )


def _week_summary(date_value):
    """Return the stored WeeklySummary for the week containing ``date_value``."""
    if isinstance(date_value, str):
        date_value = parse_date(date_value)
    if date_value is None:
        return None
    sunday = date_value + timedelta(days=6 - date_value.weekday())
    return WeeklySummary.objects.filter(date=sunday).first()


@login_required
def add_planned(request):
    summary = _week_summary(
        request.GET.get("date")
        if request.method == "GET"
        else request.POST.get("workout_date")
    )
    if request.method == "POST":
        form = PlannedWorkoutForm(request.POST)
        if form.is_valid():
            workout = form.save(commit=False)
            workout.created_by = request.user
            workout.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f"🎉 Planned {workout.get_workout_type_display().lower()} added for {workout.workout_date}.",
            )
            return redirect("alors:index")
    else:
        date = request.GET.get("date", None)
        form = PlannedWorkoutForm()
        form.fields["workout_date"].initial = date

    return render(request, "planned.html", {"form": form, "summary": summary})


@login_required
def planned_weekly_summary(request):
    """Render the weekly-summary snippet for a ``?date=YYYY-MM-DD`` query."""
    return render(
        request,
        "summary_card.html",
        {"summary": _week_summary(request.GET.get("date")), "planned": True},
    )


@login_required
def edit_planned(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    if request.method == "POST":
        form = PlannedWorkoutForm(request.POST, instance=workout)
        if form.is_valid():
            workout._notification_actor = request.user
            workout = form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f"✏️ Updated {workout.get_workout_type_display().lower()} workout for {workout.workout_date}.",
            )
            return redirect("alors:index")
        summary = _week_summary(form.data.get("workout_date"))
    else:
        form = PlannedWorkoutForm(instance=workout)
        summary = _week_summary(workout.workout_date)

    return render(
        request,
        "planned.html",
        {
            "form": form,
            "workout": workout,
            "page_title": "Edit workout",
            "page_intro": f"Update your planned {workout.get_workout_type_display().lower()} workout for {workout.workout_date}.",
            "summary": summary,
        },
    )


@login_required
def delete_planned(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    if request.method == "POST":
        label = workout.get_workout_type_display().lower()
        workout_date = workout.workout_date
        workout.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f"🗑️ Deleted {label} workout for {workout_date}.",
        )
    return redirect("alors:index")


@login_required
def planned_detail(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    Notification.objects.mark_read_for(request.user, workout)
    return render(
        request,
        "detail.html",
        {
            "workout": workout,
            "comments": workout.comments.all(),
            "comment_form": CommentForm(),
            "comment_action": "alors:add_planned_comment",
        },
    )


@login_required
def workout_detail(request, pk):
    workout = get_object_or_404(Workout, pk=pk)
    Notification.objects.mark_read_for(request.user, workout)
    fit = workout.get_workout_data()
    return render(
        request,
        "workout_detail.html",
        {
            "workout": workout,
            "route_points": json.dumps(fit.get_route_points()),
            "power_series": fit.get_power_series(),
            "elevation_series": fit.get_elevation_series(),
            "pace_series": fit.get_pace_series(),
            "heart_rate_series": fit.get_heart_rate_series(),
            "elevation_gain": fit.elevation_gain(),
            "elevation_loss": fit.elevation_loss(),
            "comments": workout.comments.all(),
            "comment_form": CommentForm(),
            "comment_action": "alors:add_workout_comment",
        },
    )


@login_required
def add_planned_comment(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.planned_workout = workout
            comment.created_by = request.user
            comment.save()
            messages.add_message(request, messages.SUCCESS, "💬 Comment added.")
    return redirect("alors:planned_detail", pk=workout.pk)


@login_required
def add_workout_comment(request, pk):
    workout = get_object_or_404(Workout, pk=pk)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.workout = workout
            comment.created_by = request.user
            comment.save()
            messages.add_message(request, messages.SUCCESS, "💬 Comment added.")
    return redirect("alors:workout_detail", pk=workout.pk)


@login_required
def workout_edit(request, pk):
    workout = get_object_or_404(Workout, pk=pk)

    if request.method == "POST":
        form = WorkoutEditForm(request.POST, instance=workout)
        if form.is_valid():
            workout._notification_actor = request.user
            if workout.created_by is None:
                workout.created_by = request.user
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                "✏️ Updated workout.",
            )
            return redirect("alors:workout_detail", pk=workout.pk)
    else:
        form = WorkoutEditForm(instance=workout)

    return render(
        request,
        "workout_form.html",
        {
            "form": form,
            "workout": workout,
            "page_title": "Edit workout",
            "page_intro": (
                f"Update the log for your "
                f"{workout.get_workout_type_display().lower()} workout"
            ),
        },
    )


def planned_webcal(request):
    """Return every planned workout as an iCalendar (.ics) document.

    The document can be downloaded and imported, or the URL subscribed to
    via the ``webcal://`` scheme in most calendar applications.
    """
    workouts = PlannedWorkout.objects.all().order_by("workout_date")
    payload = render_calendar(workouts, base_url=request.build_absolute_uri("/"))
    response = HttpResponse(payload, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="planned-workouts.ics"'
    return response


@login_required
def warmup_list(request):
    warmups = WarmUp.objects.all().order_by("title")
    return render(request, "warmup_list.html", {"warmups": warmups})


@login_required
def warmup_add(request):
    if request.method == "POST":
        form = WarmUpForm(request.POST)
        if form.is_valid():
            warmup = form.save(commit=False)
            warmup.created_by = request.user
            warmup.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'🎉 Added warm-up "{warmup.title}".',
            )
            return redirect("alors:warmup_list")
    else:
        form = WarmUpForm()

    return render(
        request,
        "warmup_form.html",
        {
            "form": form,
            "page_title": "Add a warm-up",
            "page_intro": "Write a warm-up routine you can reuse.",
        },
    )


@login_required
def warmup_edit(request, pk):
    warmup = get_object_or_404(WarmUp, pk=pk)
    if request.method == "POST":
        form = WarmUpForm(request.POST, instance=warmup)
        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'✏️ Updated warm-up "{warmup.title}".',
            )
            return redirect("alors:warmup_list")
    else:
        form = WarmUpForm(instance=warmup)

    return render(
        request,
        "warmup_form.html",
        {
            "form": form,
            "warmup": warmup,
            "page_title": "Edit warm-up",
            "page_intro": f'Update your "{warmup.title}" warm-up.',
        },
    )


@login_required
def warmup_delete(request, pk):
    warmup = get_object_or_404(WarmUp, pk=pk)
    if request.method == "POST":
        title = warmup.title
        warmup.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f'🗑️ Deleted warm-up "{title}".',
        )
    return redirect("alors:warmup_list")


@login_required
def issue_list(request):
    issues = Issue.objects.all().order_by("title")
    return render(request, "issue_list.html", {"issues": issues})


@login_required
def issue_add(request):
    if request.method == "POST":
        form = IssueForm(request.POST)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.created_by = request.user
            issue.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'🎉 Added issue "{issue.title}".',
            )
            return redirect("alors:issue_list")
    else:
        form = IssueForm()

    return render(
        request,
        "issue_form.html",
        {
            "form": form,
            "page_title": "Add an issue",
            "page_intro": "Report a new issue or bug.",
        },
    )


@login_required
def issue_edit(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    if request.method == "POST":
        form = IssueForm(request.POST, instance=issue)
        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'✏️ Updated issue "{issue.title}".',
            )
            return redirect("alors:issue_list")
    else:
        form = IssueForm(instance=issue)

    return render(
        request,
        "issue_form.html",
        {
            "form": form,
            "issue": issue,
            "page_title": "Edit issue",
            "page_intro": f'Update your "{issue.title}" issue.',
        },
    )


@login_required
def issue_delete(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    if request.method == "POST":
        title = issue.title
        issue.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f'🗑️ Deleted issue "{title}".',
        )
    return redirect("alors:issue_list")


@login_required
def label_list(request):
    labels = Label.objects.all().order_by("start_date", "title")
    return render(request, "label_list.html", {"labels": labels})


@login_required
def label_add(request):
    if request.method == "POST":
        form = LabelForm(request.POST)
        if form.is_valid():
            label = form.save(commit=False)
            label.created_by = request.user
            label.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'🎉 Added label "{label.title}".',
            )
            return redirect("alors:label_list")
    else:
        form = LabelForm()

    return render(
        request,
        "label_form.html",
        {
            "form": form,
            "page_title": "Add a label",
            "page_intro": "Create a labelled date range.",
        },
    )


@login_required
def label_edit(request, pk):
    label = get_object_or_404(Label, pk=pk)
    if request.method == "POST":
        form = LabelForm(request.POST, instance=label)
        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'✏️ Updated label "{label.title}".',
            )
            return redirect("alors:label_list")
    else:
        form = LabelForm(instance=label)

    return render(
        request,
        "label_form.html",
        {
            "form": form,
            "label": label,
            "page_title": "Edit label",
            "page_intro": f'Update your "{label.title}" label.',
        },
    )


@login_required
def label_delete(request, pk):
    label = get_object_or_404(Label, pk=pk)
    if request.method == "POST":
        title = label.title
        label.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f'🗑️ Deleted label "{title}".',
        )
    return redirect("alors:label_list")


@login_required
def edit_profile(request):
    """Let the logged-in user edit their own role and email address."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(
            request.POST, request.FILES, instance=profile, user=request.user
        )
        if form.is_valid():
            form.save()
            messages.add_message(request, messages.SUCCESS, "🙋 Profile updated.")
            return redirect("alors:profile")
    else:
        form = ProfileForm(instance=profile, user=request.user)

    return render(
        request,
        "profile_form.html",
        {
            "form": form,
            "page_title": "Your profile",
            "page_intro": "Choose your role and keep your email address up to date.",
        },
    )


@login_required
def notifications(request):
    """List all notifications for the logged-in user."""
    items = request.user.notifications.filter(read=False)
    return render(
        request,
        "notifications.html",
        {
            "notifications": items,
            "unread_count": items.count(),
        },
    )


@login_required
def mark_all_notifications_read(request):
    """Mark every notification for the logged-in user as read."""
    if request.method == "POST":
        count = request.user.notifications.filter(read=False).update(read=True)
        messages.add_message(
            request,
            messages.SUCCESS,
            f"✅ Marked {count} notification"
            + ("s" if count != 1 else "")
            + " as read.",
        )
    return redirect("alors:notifications")


def styles(request):
    return render(request, "styles.html")
