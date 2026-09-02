"""Generate an RFC 5545 (iCalendar) document for planned workouts.

Uses the third-party ``icalendar`` library. The public ``render_calendar``
function turns an iterable of planned workouts into a ``VCALENDAR`` of
all-day ``VEVENT``s that calendar applications (Google Calendar, Apple
Calendar, Outlook, ...) can import or subscribe to.
"""
from datetime import timedelta

from icalendar import Calendar, Event

PRODID = "-//Glute Alors//Planned Workouts//EN"


def _description(workout):
    """Build the human-readable DESCRIPTION text for a workout."""
    parts = [f"{workout.total_distance} km planned"]
    if workout.warm_up:
        parts.append(f"Warm up: {workout.warm_up.text}")
    if workout.notes:
        parts.append(workout.notes)
    return "\n".join(parts)


def _summary(workout):
    """A short event summary, preferring the workout title."""
    if workout.title:
        return workout.title
    return f"{workout.get_workout_type_display()} workout"


def _add_event(calendar, workout, base_url):
    event = Event()
    event.add("uid", f"planned-workout-{workout.pk}@glute-alors")
    event.add("dtstamp", workout.updated_at)
    event.add("dtstart", workout.workout_date)
    event.add("dtend", workout.workout_date + timedelta(days=1))
    event.add("summary", _summary(workout))
    event.add("description", _description(workout))
    event.add("transp", "TRANSPARENT")
    event.add("status", "CONFIRMED")
    if base_url:
        event.add("url", base_url.rstrip("/") + workout.get_absolute_url())
    calendar.add_component(event)


def render_calendar(workouts, base_url="", calendar_name="Planned workouts"):
    """Render an iterable of workouts to an iCalendar document (a string)."""
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", calendar_name)
    calendar.add("x-wr-caldesc", "Workouts planned in Glute Alors")

    for workout in workouts:
        _add_event(calendar, workout, base_url)

    return calendar.to_ical().decode("utf-8")
