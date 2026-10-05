from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from .forms import (
    CalendarForm,
    CommentForm,
    IssueForm,
    LabelForm,
    PlannedWorkoutForm,
    PlannedWorkoutModalForm,
    PlannedWorkoutUpdateForm,
    ProfileForm,
    SavedWorkoutForm,
    WorkoutEditForm,
)
from .models import (
    Notification,
    Workout,
    PlannedWorkout,
    SavedWorkout,
    Issue,
    Label,
    UserProfile,
    WeeklySummary,
)
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import date, datetime, timedelta
from decimal import Decimal

from .validators import validate_date
from .ical import render_calendar
from itertools import chain
from .utils import dateList, combineDateLists
from .emails import email_as_text
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
    query = {
        "d": request.GET.get("d", request.COOKIES.get("d", "")),
        "r": request.GET.get("r", request.COOKIES.get("r", "")),
    }
    form = CalendarForm(query, request=request)
    form.is_valid()
    date = form.cleaned_data["d"]
    template = "weekly.html" if form.cleaned_data["r"] == "w" else "monthly.html"
    dates = form.cleaned_data["start_end_dates"]
    list_dates = form.cleaned_data["list_dates"]

    # Note: use __lt to ensure we get runs up to midnight the last day.
    # ``workout_data`` is deferred: it can be several megabytes per workout and
    # the calendar cards never read it.
    planned_workouts = dateList(
        PlannedWorkout.objects.filter(
            workout_date__gte=dates["start"],
            workout_date__lt=dates["next"],
        ).order_by("workout_date")
    )

    actual_workouts = dateList(
        Workout.objects.filter(
            workout_date__gte=dates["start"], workout_date__lt=dates["next"]
        )
        .defer("workout_data")
        .order_by("workout_date")
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

    # ``Workout.get_planned`` is read several times per card in the template.
    # Answer it from the planned workouts already fetched for this range, so
    # rendering the calendar does not run a query per workout card.
    planned_by_date = {}
    for workouts in planned_workouts.values():
        for planned in workouts:
            key = planned.get_date_as_str()
            current = planned_by_date.get(key)
            if current is None or planned.created_at > current.created_at:
                planned_by_date[key] = planned
    for workouts in actual_workouts.values():
        for workout in workouts:
            workout.get_planned = (
                planned_by_date.get(workout.get_date_as_str())
                if workout.workout_type == "run"
                else None
            )

    results = combineDateLists(
        list_dates,
        planned=planned_workouts,
        actual=actual_workouts,
        summaries=summaries,
        labels=labels,
    )

    # If the monthly, split the data into weeks to make the template easier.
    if form.cleaned_data["r"] == "m":
        results = [results[i:i + 7] for i in range(0, len(results), 7)]

    # The add and edit modals share one set of saved-workout choices, read
    # once so a page full of modals does not query for each form.
    saved_workout_choices = []
    saved_workout_texts = {}
    for pk, title, text in SavedWorkout.objects.values_list("pk", "title", "text"):
        saved_workout_choices.append((str(pk), title))
        saved_workout_texts[str(pk)] = text

    add_planned_form = PlannedWorkoutModalForm(
        saved_workout_choices=saved_workout_choices,
        saved_workout_texts=saved_workout_texts,
    )

    planned_edit_forms = [
        (
            workout,
            PlannedWorkoutModalForm(
                instance=workout,
                auto_id=f"edit-{workout.pk}-%s",
                saved_workout_choices=saved_workout_choices,
                saved_workout_texts=saved_workout_texts,
            ),
        )
        for workouts in planned_workouts.values()
        for workout in workouts
    ]

    response = render(
        request,
        template,
        {
            "today": dates["today"],
            "date": date,
            "next": dates["next"],
            "previous": dates["previous"],
            "dates_and_objects": results,
            "planned_edit_forms": planned_edit_forms,
            "add_planned_form": add_planned_form,
            "template": "monthly" if form.cleaned_data["r"] == "m" else "weekly",
        },
    )
    for cookie in ["d", "r"]:
        value = form.cleaned_data.get(cookie, "")
        if value:
            response.set_cookie(cookie, value)
        else:
            response.delete_cookie(cookie)
    return response

def _week_summary(date_value):
    """Return the stored WeeklySummary for the week containing ``date_value``."""

    if date_value is None:
        return None
    sunday = date_value + timedelta(days=6 - date_value.weekday())
    return WeeklySummary.objects.filter(date=sunday).first()


@login_required
def add_planned(request):
    date = (
        request.GET.get("date")
        if request.method == "GET"
        else request.POST.get("workout_date")
    )
    date_value = parse_date(date) if isinstance(date, str) else None
    this_week_summary = _week_summary(date_value)
    last_week_summary = (
        _week_summary(date_value - timedelta(days=7)) if date_value else None
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
            return redirect(f"/calendar/?d={date}#date-{workout.workout_date}")
    else:
        date = request.GET.get("date", None)
        form = PlannedWorkoutForm()
        form.fields["workout_date"].initial = date

    return render(
        request,
        "planned_add.html",
        {
            "form": form,
            "this_week_summary": this_week_summary,
            "last_week_summary": last_week_summary,
        },
    )


@login_required
def planned_weekly_summary(request):
    """Render the weekly-summary snippet for a ``?date=YYYY-MM-DD`` query."""
    return render(
        request,
        "summary_card.html",
        {
            "summary": _week_summary(parse_date(request.GET.get("date"))),
            "planned": True,
        },
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
            return redirect(f"/calendar/?d={workout.workout_date}#date-{workout.workout_date}")
        
    else:
        form = PlannedWorkoutForm(instance=workout)

    summary = _week_summary(workout.workout_date)
    return render(
        request,
        "planned_add.html",
        {
            "form": form,
            "workout": workout,
            "page_title": "Edit workout",
            "page_intro": f"Update your planned {workout.get_workout_type_display().lower()} workout for {workout.workout_date}.",
            "summary": summary,
        },
    )


@login_required
@require_POST
def delete_planned(request, pk):
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    label = workout.get_workout_type_display().lower()
    workout_date = workout.workout_date
    workout.delete()
    messages.add_message(
        request,
        messages.SUCCESS,
        f"🗑️ Deleted {label} workout for {workout_date}.",
    )
    return redirect(f"/calendar/?d={workout_date}#date-{workout_date}")


# Fields the calendar JSON endpoint is allowed to change on a planned workout.
PLANNED_API_FIELDS = (
    "title",
    "workout_type",
    "is_race",
    "workout_date",
    "total_distance",
    "notes",
)


def _planned_workout_data(request):
    """Return the request body as a plain dict, supporting form and JSON posts.

    ``None`` is returned when a JSON body is present but not a JSON object.
    """
    data = request.POST.dict()
    if request.content_type == "application/json" and request.body:
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        data.update(payload)
    return data


def _json_value(value):
    """Coerce a model field value into something ``JsonResponse`` can encode."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@login_required
@require_POST
def duplicate_planned(request, pk):
    """Create a copy of a planned workout on the same day."""
    workout = get_object_or_404(PlannedWorkout, pk=pk)
    label = workout.get_workout_type_display().lower()
    workout_date = workout.workout_date

    # Re-insert the same row as a new object, resetting the fields that belong
    # to the original rather than the copy.
    workout.pk = None
    workout._state.adding = True
    workout.status = ""
    workout.comment_count = 0
    workout.created_by = request.user
    workout.save()

    messages.add_message(
        request,
        messages.SUCCESS,
        f"📋 Duplicated {label} workout for {workout_date}.",
    )
    return redirect(f"/calendar/?d={workout_date}#date-{workout_date}")


@login_required
@require_POST
def move_planned_workout(request, pk):
    """Move or edit a planned workout from the calendar.

    The drag and drop sends ``date``; the same endpoint also accepts any of
    ``title``, ``workout_type``, ``is_race``, ``total_distance`` and ``notes``,
    so a workout can be edited without posting the whole form. Only the fields
    that are supplied are changed; saving refreshes the weekly summaries.
    """
    workout = get_object_or_404(PlannedWorkout, pk=pk)

    data = _planned_workout_data(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    # ``date`` is the name the calendar sends; accept the model field too.
    if "date" in data and "workout_date" not in data:
        data["workout_date"] = data.pop("date")

    posted = [field for field in PLANNED_API_FIELDS if field in data]
    if not posted:
        return JsonResponse({"error": "No fields to update."}, status=400)

    # Seed the form with the stored values so it behaves as a partial update.
    for field in PLANNED_API_FIELDS:
        data.setdefault(field, getattr(workout, field))

    form = PlannedWorkoutUpdateForm(data, instance=workout)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    workout = form.save()

    response = {"id": workout.pk, "date": workout.workout_date.isoformat()}
    for field in posted:
        # The date is already reported as "date" above.
        if field != "workout_date":
            response[field] = _json_value(getattr(workout, field))
    return JsonResponse(response)


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
    fit = workout.get_workout_data
    return render(
        request,
        "workout_detail.html",
        {
            "workout": workout,
            "planned": workout.get_planned,
            "route_points": json.dumps(fit.get_route_points()),
            "power_series": fit.get_power_series(),
            "elevation_series": fit.get_elevation_series(),
            "pace_series": fit.get_pace_series(),
            "heart_rate_series": fit.get_heart_rate_series(),
            "elevation_gain": fit.elevation_gain(),
            "elevation_loss": fit.elevation_loss(),
            "comments": workout.comments.all(),
            "recorded_on": fit.get_recorded_on(),
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
def saved_workout_list(request):
    saved_workouts = SavedWorkout.objects.all().order_by("title")
    return render(
        request, "saved_workout_list.html", {"saved_workouts": saved_workouts}
    )


@login_required
def saved_workout_add(request):
    if request.method == "POST":
        form = SavedWorkoutForm(request.POST)
        if form.is_valid():
            saved_workout = form.save(commit=False)
            saved_workout.created_by = request.user
            saved_workout.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'🎉 Added saved workout "{saved_workout.title}".',
            )
            return redirect("alors:saved_workout_list")
    else:
        form = SavedWorkoutForm()

    return render(
        request,
        "saved_workout_form.html",
        {
            "form": form,
            "page_title": "Add a saved workout",
            "page_intro": "Write a workout you can reuse.",
        },
    )


@login_required
def saved_workout_edit(request, pk):
    saved_workout = get_object_or_404(SavedWorkout, pk=pk)
    if request.method == "POST":
        form = SavedWorkoutForm(request.POST, instance=saved_workout)
        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'✏️ Updated saved workout "{saved_workout.title}".',
            )
            return redirect("alors:saved_workout_list")
    else:
        form = SavedWorkoutForm(instance=saved_workout)

    return render(
        request,
        "saved_workout_form.html",
        {
            "form": form,
            "saved_workout": saved_workout,
            "page_title": "Edit saved workout",
            "page_intro": f'Update your "{saved_workout.title}" workout.',
        },
    )


@login_required
def saved_workout_delete(request, pk):
    saved_workout = get_object_or_404(SavedWorkout, pk=pk)
    if request.method == "POST":
        title = saved_workout.title
        saved_workout.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f'🗑️ Deleted saved workout "{title}".',
        )
    return redirect("alors:saved_workout_list")


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
            "page_intro": "Choose your role and timezone, and keep your email address up to date.",
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
 

@login_required
def email_html(request):
    text = email_as_text(request.user) or ""
    lines = []
    for line in text.split("\n"):
        line = line.rstrip()
        lines.append(line)
    
    return render(request, "email.html", {"text": "\n".join(lines)})

def styles(request):
    return render(request, "styles.html")

@login_required
def error(request):
    return 1/0

from django.core.exceptions import PermissionDenied
@login_required
def nope(request):
    raise PermissionDenied