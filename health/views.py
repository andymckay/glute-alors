from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .forms import HealthForm
from .models import Health

PAGE_SIZE = 25


@login_required
def health_list(request):
    paginator = Paginator(Health.objects.all(), PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "health/health_list.html",
        {"records": page_obj, "page_obj": page_obj},
    )


@login_required
def health_add(request):
    if request.method == "POST":
        form = HealthForm(request.POST)
        if form.is_valid():
            health = form.save(commit=False)
            health.created_by = request.user
            health.save()
            messages.add_message(request, messages.SUCCESS, "🎉 Added health entry.")
            return redirect("health:health_list")
    else:
        form = HealthForm()

    return render(
        request,
        "health/health_form.html",
        {
            "form": form,
            "page_title": "Add a health entry",
            "page_intro": "Record your weight, blood pressure and resting heart rate.",
        },
    )


@login_required
def health_edit(request, pk):
    health = get_object_or_404(Health, pk=pk)
    if request.method == "POST":
        form = HealthForm(request.POST, instance=health)
        if form.is_valid():
            form.save()
            messages.add_message(request, messages.SUCCESS, "✏️ Updated health entry.")
            return redirect("health:health_list")
    else:
        form = HealthForm(instance=health)

    return render(
        request,
        "health/health_form.html",
        {
            "form": form,
            "health": health,
            "page_title": "Edit health entry",
            "page_intro": "Update this health entry.",
        },
    )


@login_required
def health_delete(request, pk):
    health = get_object_or_404(Health, pk=pk)
    if request.method == "POST":
        health.delete()
        messages.add_message(request, messages.SUCCESS, "🗑️ Deleted health entry.")
    return redirect("health:health_list")
