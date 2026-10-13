from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import (
    DEFAULT_REST_SECONDS,
    DefaultWeightsWorkoutSetFormSet,
    WeightsWorkoutExerciseFormSet,
    WeightsWorkoutForm,
    WeightsWorkoutSetForm,
    WeightsWorkoutSetFormSet,
    parse_seconds,
)
from alors.models import UserProfile

from .models import (
    Exercise,
    WeightsWorkout,
    WeightsWorkoutExercise,
    WeightsWorkoutSet,
    WeightsWorkoutSuperset,
    format_seconds,
)

# How the profile's weight units are shown next to a weight input.
UNIT_ABBREVIATIONS = {
    UserProfile.WeightUnit.METRIC: "kg",
    UserProfile.WeightUnit.IMPERIAL: "lb",
}


def _is_timed(exercise_id):
    """Whether the catalogue exercise with this id is measured in time."""
    try:
        return int(exercise_id) in Exercise.timed_ids()
    except (TypeError, ValueError):
        return False


def _superset_letter(form):
    """The superset letter a row is showing, from the data or its instance."""
    return (form["superset"].value() or "").strip().upper()


def _superset_rest(data, letter):
    """The rest posted for a superset, in seconds, or ``None``."""
    try:
        return parse_seconds(data.get(f"superset-{letter}-rest")) or None
    except ValueError:
        return None


def _weight_unit_abbr(request):
    """The abbreviation ("kg"/"lb") for the request user's preferred units."""
    profile = getattr(request.user, "profile", None)
    units = profile.units if profile else UserProfile.WeightUnit.IMPERIAL
    return UNIT_ABBREVIATIONS.get(units, units)


def _set_formsets(exercise_forms, data=None, actual=False):
    """One set formset per exercise row, each with its own ``sets<i>`` prefix.

    A new exercise gets a few prefilled set rows; an existing one only the
    sets that were saved. Each formset knows whether its exercise is timed,
    which decides between reps and minutes/seconds, and whether the workout is
    an actual one, which adds a box to tick each set off.
    """
    formsets = []
    for index, form in enumerate(exercise_forms):
        exercise_id = (
            form.instance.exercise_id
            if data is None
            else data.get(form.add_prefix("exercise_id"))
        )
        timed = _is_timed(exercise_id)
        factory = (
            WeightsWorkoutSetFormSet
            if form.instance.pk
            else DefaultWeightsWorkoutSetFormSet
        )
        formset = factory(
            data,
            instance=form.instance,
            prefix=f"sets{index}",
            form_kwargs={"timed": timed, "actual": actual},
        )
        formset.timed = timed
        formsets.append(formset)
    return formsets


def _form_context(formset, set_formsets, data=None, supersets=None, actual=False):
    """Template context for the nested exercise/set rows.

    Rows are gathered into superset groups in render order; a group's rest is
    read from the posted inputs, or from the superset it was saved as.
    """
    rows = [
        {
            "form": form,
            "set_formset": set_formset,
            "timed": set_formset.timed,
            "letter": _superset_letter(form),
        }
        for form, set_formset in zip(formset.forms, set_formsets)
    ]
    groups = {}
    ordered = []
    for row in rows:
        letter = row["letter"]
        if not letter:
            ordered.append({"letter": "", "rows": [row]})
        elif letter in groups:
            groups[letter]["rows"].append(row)
        else:
            groups[letter] = {"letter": letter, "rows": [row]}
            ordered.append(groups[letter])

    for group in ordered:
        letter = group["letter"]
        if not letter:
            continue
        superset = (supersets or {}).get(letter)
        if data is not None:
            saved = _superset_rest(data, letter)
        elif superset is not None:
            saved = superset.rest_seconds
        else:
            saved = None
        if saved is None and superset is None:
            # A group the JS just made: start it off with the default rest.
            saved = DEFAULT_REST_SECONDS
        group["rest"] = format_seconds(saved)

    return {
        "groups": ordered,
        "empty_exercise_form": formset.empty_form,
        # A placeholder formset whose prefix the JS swaps for a real index.
        "empty_set_formset": DefaultWeightsWorkoutSetFormSet(
            prefix="sets__exercise__",
            instance=WeightsWorkoutExercise(),
            form_kwargs={"timed": False, "actual": actual},
        ),
        # Prefilled into the superset header the JS clones.
        "default_rest": format_seconds(DEFAULT_REST_SECONDS),
    }


def _save_sets(set_formset, entry, superset=False):
    """Persist one exercise's sets, renumbering ``position`` by row order.

    A superset rests at the end of each round, so its exercises' sets keep no
    rest of their own.
    """
    position = 0
    for form in set_formset.forms:
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            if form.cleaned_data.get("DELETE") and form.instance.pk:
                form.instance.delete()
            continue
        if form.timed:
            if not form.total_duration():
                continue
        elif form.cleaned_data.get("reps") is None:
            continue
        model_set = form.save(commit=False)
        if superset:
            model_set.rest_seconds = None
        model_set.entry = entry
        model_set.position = position
        model_set.save()
        position += 1
    if superset:
        # Sets the form skipped still hold the rest they were saved with.
        entry.sets.update(rest_seconds=None)


def _save_supersets(workout, rows, data):
    """Sync the workout's supersets with the letters its rows are grouped by.

    An exercise only counts as part of a superset when a letter is shared with
    another row, so a lone one drops back out. Returns the letter to superset
    map for the rows that stay grouped.
    """
    letters = [letter for letter, _, _ in rows]
    counts = Counter(letters)
    supersets = {}
    for letter in dict.fromkeys(letters):
        if not letter or counts[letter] < 2:
            continue
        supersets[letter] = WeightsWorkoutSuperset.objects.update_or_create(
            workout=workout,
            letter=letter,
            defaults={"rest_seconds": _superset_rest(data, letter)},
        )[0]
    workout.supersets.exclude(letter__in=supersets).delete()
    return supersets


def _save_exercises(formset, set_formsets, workout, data=None):
    """Persist the exercise rows, their supersets and their sets."""
    rows = []
    for form, set_formset in zip(formset.forms, set_formsets):
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            if form.cleaned_data.get("DELETE") and form.instance.pk:
                form.instance.delete()
            continue
        if not form.cleaned_data.get("exercise_id"):
            continue
        entry = form.save(commit=False)
        entry.workout = workout
        entry.position = len(rows)
        rows.append((form.cleaned_data.get("superset") or "", entry, set_formset))

    supersets = _save_supersets(workout, rows, data)
    for letter, entry, set_formset in rows:
        entry.superset = supersets.get(letter)
        entry.save()
        _save_sets(set_formset, entry, superset=entry.superset_id is not None)


def _copy_workout(workout, created_by, title, plan=None, is_actual=False):
    """Copy a workout's supersets, exercises and sets into a new workout.

    The copy starts with nothing ticked off, so it can be done or edited
    without disturbing what the original recorded.
    """
    copy = WeightsWorkout.objects.create(
        created_by=created_by, title=title, plan=plan, is_actual=is_actual
    )
    supersets = {
        superset.pk: WeightsWorkoutSuperset.objects.create(
            workout=copy,
            letter=superset.letter,
            rest_seconds=superset.rest_seconds,
        )
        for superset in workout.supersets.all()
    }
    for entry in workout.exercises.all():
        new_entry = WeightsWorkoutExercise.objects.create(
            workout=copy,
            exercise_id=entry.exercise_id,
            position=entry.position,
            superset=supersets.get(entry.superset_id),
        )
        for model_set in entry.sets.all():
            WeightsWorkoutSet.objects.create(
                entry=new_entry,
                reps=model_set.reps,
                weight=model_set.weight,
                duration_seconds=model_set.duration_seconds,
                rest_seconds=model_set.rest_seconds,
                position=model_set.position,
            )
    return copy


def _exercise_detail_url():
    """The exercise details URL as a template the rows can fill an id into."""
    return reverse("weights:exercise_detail", args=[0]).replace("/0/", "/__id__/")


@login_required
def exercise_detail(request, exercise_id):
    """The catalogue's description and picture for one exercise."""
    exercise = Exercise.get(exercise_id)
    if exercise is None:
        raise Http404("No such exercise.")
    return JsonResponse(
        {
            "id": exercise.id,
            "name": exercise.name,
            "description": exercise.instructions,
            "image": exercise.image_url,
        }
    )


@login_required
def workout_list(request):
    workouts = WeightsWorkout.objects.filter(is_actual=False).prefetch_related(
        "exercises__sets", "exercises__superset"
    )
    return render(
        request,
        "weights_list.html",
        {
            "workouts": workouts,
            "weight_unit_abbr": _weight_unit_abbr(request),
        },
    )


@login_required
def workout_add(request):
    data = request.POST if request.method == "POST" else None
    if data is not None:
        form = WeightsWorkoutForm(data)
        formset = WeightsWorkoutExerciseFormSet(data)
        set_formsets = _set_formsets(formset.forms, data)
        if (
            form.is_valid()
            and formset.is_valid()
            and all(set_formset.is_valid() for set_formset in set_formsets)
        ):
            workout = form.save(commit=False)
            workout.created_by = request.user
            workout.save()
            _save_exercises(formset, set_formsets, workout, data)
            messages.add_message(
                request, messages.SUCCESS, "🎉 Created weights workout."
            )
            return redirect("weights:workout_list")
    else:
        form = WeightsWorkoutForm()
        formset = WeightsWorkoutExerciseFormSet()
        set_formsets = _set_formsets(formset.forms)

    context = _form_context(formset, set_formsets, data)
    context.update(
        {
            "form": form,
            "formset": formset,
            "page_title": "Create a weights workout",
            "page_intro": "Add one or more exercises and the sets you did.",
            "weight_unit_abbr": _weight_unit_abbr(request),
            "timed_exercise_ids": sorted(Exercise.timed_ids()),
            "exercise_detail_url": _exercise_detail_url(),
            "actual": False,
        }
    )
    return render(request, "weights_form.html", context)


@login_required
def workout_edit(request, pk):
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    supersets = {superset.letter: superset for superset in workout.supersets.all()}
    data = request.POST if request.method == "POST" else None
    if data is not None:
        form = WeightsWorkoutForm(data, instance=workout)
        formset = WeightsWorkoutExerciseFormSet(data, instance=workout)
        set_formsets = _set_formsets(formset.forms, data, workout.is_actual)
        if (
            form.is_valid()
            and formset.is_valid()
            and all(set_formset.is_valid() for set_formset in set_formsets)
        ):
            form.save()
            _save_exercises(formset, set_formsets, workout, data)
            if workout.is_actual:
                # Ticking the last set off here finishes the workout too.
                workout.mark_finished()
            messages.add_message(
                request, messages.SUCCESS, "✏️ Updated weights workout."
            )
            if workout.is_actual:
                return redirect("weights:workout_edit", workout.pk)
            return redirect("weights:workout_list")
    else:
        form = WeightsWorkoutForm(instance=workout)
        formset = WeightsWorkoutExerciseFormSet(instance=workout)
        set_formsets = _set_formsets(formset.forms, actual=workout.is_actual)

    context = _form_context(formset, set_formsets, data, supersets, workout.is_actual)
    context.update(
        {
            "form": form,
            "formset": formset,
            "workout": workout,
            "page_title": "Edit weights workout",
            "page_intro": "Update this workout's title, exercises and sets.",
            "weight_unit_abbr": _weight_unit_abbr(request),
            "timed_exercise_ids": sorted(Exercise.timed_ids()),
            "exercise_detail_url": _exercise_detail_url(),
            "actual": workout.is_actual,
        }
    )
    return render(request, "weights_form.html", context)


@login_required
def workout_do(request, pk):
    """Start a planned workout, leaving the plan itself alone."""
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    if request.method == "POST":
        actual = _copy_workout(
            workout,
            created_by=request.user,
            title=workout.title,
            plan=workout.plan or workout,
            is_actual=True,
        )
        actual.mark_started()
        return redirect("weights:workout_perform", actual.pk)
    return redirect("weights:workout_edit", workout.pk)


@login_required
def workout_perform(request, pk):
    """Do a workout: one set at a time, resting between them.

    Each action posts back here, so the page works without JavaScript as a
    plain form; with JavaScript the ticks are sent in the background and the
    rest is counted down.
    """
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    if not workout.is_actual:
        # A plan is a blueprint; doing one starts an actual workout.
        return redirect("weights:workout_edit", workout.pk)
    # An actual workout that has no start yet (one made by hand, say) is
    # started now that it is being done.
    workout.mark_started()
    if request.method == "POST":
        return _perform_action(request, workout)

    steps = workout.steps()
    # The set to open on: the first one still to do.
    current_index = next(
        (index for index, step in enumerate(steps) if not step.done), 0
    )
    current_entry_pk = steps[current_index].entry.pk if steps else None
    return render(
        request,
        "weights_perform.html",
        {
            "workout": workout,
            "steps": steps,
            # One exercise at a time: the exercises not being done are hidden.
            "step_groups": [
                {
                    "entry": entry,
                    "steps": group,
                    "timed": group[0].timed,
                    # Shown when the whole workout is on show, in place of the
                    # exercise's sets.
                    "done": sum(1 for step in group if step.done),
                    "total": len(group),
                    "current": entry.pk == current_entry_pk,
                }
                for entry, group in workout.step_groups()
            ],
            "current_index": current_index,
            "current_set_pk": steps[current_index].set.pk if steps else None,
            "done_count": sum(1 for step in steps if step.done),
            "total_count": len(steps),
            "weight_unit_abbr": _weight_unit_abbr(request),
        },
    )


def _logged_values(request, model_set):
    """What to save for a set being logged, as the set form expects it.

    The page sends the reps, weight or time as they were entered; a field it did
    not send, and the rest it does not show, keep the set's own values.
    """
    values = {
        "reps": model_set.reps,
        "weight": model_set.weight,
        "duration": format_seconds(model_set.duration_seconds),
        "rest": format_seconds(model_set.rest_seconds),
    }
    for name in ("reps", "weight", "duration"):
        posted = request.POST.get(f"set-{model_set.pk}-{name}")
        if posted is not None:
            values[name] = posted
    return values


def _next_set_to_log(workout, entry_id=None):
    """The first set still to do, of one exercise when the page picked one."""
    steps = workout.steps()
    if entry_id:
        steps = [step for step in steps if str(step.entry.pk) == str(entry_id)]
    step = next((step for step in steps if not step.done), None)
    return step.set if step else None


def _next_set_position(entry):
    """Where a set added from the page goes: after the exercise's last one."""
    last = entry.sets.order_by("-position").first()
    return last.position + 1 if last else 0


def _perform_action(request, workout):
    """Handle one change made while doing a workout."""
    action = request.POST.get("action")
    # A log counts the first set still to do, of the exercise the page picked
    # if it picked one, whatever row it was posted from.
    model_set = (
        _next_set_to_log(workout, request.POST.get("entry"))
        if action == "log"
        else get_object_or_404(
            WeightsWorkoutSet, pk=request.POST.get("set"), entry__workout=workout
        )
    )
    form = None
    if action == "delete":
        model_set.delete()
    elif action == "save":
        # Leave the set's done flag alone: this only edits the target.
        form = WeightsWorkoutSetForm(
            request.POST,
            instance=model_set,
            timed=_is_timed(model_set.entry.exercise_id),
        )
        if form.is_valid():
            form.save()
    elif action == "log":
        if model_set is not None:
            # What the page entered for this set is what gets logged.
            form = WeightsWorkoutSetForm(
                _logged_values(request, model_set),
                instance=model_set,
                timed=_is_timed(model_set.entry.exercise_id),
            )
            if form.is_valid():
                form.save()
                model_set.completed = True
                model_set.save(update_fields=["completed"])
    elif action == "add":
        # Another set like this one, left to do, at the end of its exercise.
        form = WeightsWorkoutSetForm(
            _logged_values(request, model_set),
            timed=_is_timed(model_set.entry.exercise_id),
        )
        if form.is_valid():
            added = form.save(commit=False)
            added.entry = model_set.entry
            added.position = _next_set_position(model_set.entry)
            added.save()
    elif model_set is not None:
        model_set.completed = action == "complete"
        model_set.save(update_fields=["completed"])
    workout.mark_finished()

    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect("weights:workout_perform", workout.pk)

    steps = workout.steps()
    return JsonResponse(
        {
            "ok": form is None or form.is_valid(),
            "action": action,
            "deleted": action == "delete",
            "completed": getattr(model_set, "completed", False),
            # The set the action landed on, so the page can tick its row off.
            "set": model_set.pk if model_set is not None else None,
            "done_count": sum(1 for step in steps if step.done),
            "total_count": len(steps),
            # Whether the workout itself is finished, not the set.
            "finished": workout.completed,
            "errors": form.errors if form is not None else {},
        }
    )


@login_required
def workout_complete(request, pk):
    """Finish an actual workout by hand, or reopen one that was finished."""
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    if request.method == "POST" and workout.is_actual:
        if workout.completed:
            workout.reopen()
            messages.add_message(
                request, messages.SUCCESS, "↩️ Reopened weights workout."
            )
        else:
            workout.complete()
            messages.add_message(
                request, messages.SUCCESS, "🏁 Completed weights workout."
            )
            # A finished workout is over: go and look at the day it landed on.
            # It was finished just now, so that day is today: the calendar's
            # "Today" link, with any stored date cleared so it cannot open on
            # some other week.
            return redirect(f"{reverse('alors:calendar')}?d=#today")
    return redirect("weights:workout_perform", workout.pk)


@login_required
def workout_duplicate(request, pk):
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    if request.method == "POST":
        duplicate = _copy_workout(
            workout,
            created_by=request.user,
            title=workout.title,
        )
        messages.add_message(request, messages.SUCCESS, "📋 Duplicated weights workout.")
        return redirect("weights:workout_edit", duplicate.pk)
    return redirect("weights:workout_edit", workout.pk)


@login_required
def workout_delete(request, pk):
    workout = get_object_or_404(WeightsWorkout, pk=pk)
    if request.method == "POST":
        workout.delete()
        messages.add_message(request, messages.SUCCESS, "🗑️ Deleted weights workout.")
    return redirect("weights:workout_list")
