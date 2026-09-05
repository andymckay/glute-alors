from django import template
from django.utils.safestring import mark_safe
import json
import time

emojis = {"run": "🏃‍♀", "walk": "🚶", "hike": "👢", "strength": "🏋", "recovery": "❤️"}


def emoji(value):
    return emojis.get(value.lower())


def hms(seconds):
    string = time.strftime("%H:%M:%S", time.gmtime(seconds))
    # Strip leading 0 and : if needed.
    if string.startswith("0"):
        return string[1:]
    if string.startswith("0:"):
        return string[2:]
    if string.startswith("00:"):
        return string[3:]
    return string


def status(value):
    return {
        "missed": "danger",
        "under": "warning",
        "over": "warning",
        "done": "success",
    }.get(value.lower())


def _line_chart_svg(series, stroke, metric, average_label, inverted=False):
    """Build an SVG line chart (not yet marked safe).

    When ``inverted`` is true the y axis is flipped so the smallest value is
    drawn at the top (used for pace, where a smaller number is better).
    """
    if len(series) < 2:
        return ""
    values = [value for _, value in series]
    low, high = min(values), max(values)
    if high - low < 1:
        high = low + 1

    width, height = 600, 100
    pad_left, pad_right, pad_top, pad_bottom = 8, 8, 16, 16
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom

    def x_at(index):
        return pad_left + plot_width * index / (len(series) - 1)

    def y_at(value):
        fraction = (value - low) / (high - low)
        if inverted:
            return pad_top + plot_height * fraction
        return pad_top + plot_height * (1 - fraction)

    points = " ".join(
        f"{x_at(index):.1f},{y_at(value):.1f}"
        for index, (_, value) in enumerate(series)
    )
    average = sum(values) / len(values)
    last_seconds = series[-1][0]
    series_json = json.dumps([[sec, value] for sec, value in series])

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'class="hr-chart img-fluid" '
        f'data-series=\'{series_json}\' data-metric="{metric}" '
        f'aria-label="Chart" style="cursor: crosshair">'
        f'<line x1="{pad_left:.1f}" y1="{y_at(average):.1f}" '
        f'x2="{width - pad_right:.1f}" y2="{y_at(average):.1f}" '
        f'stroke="#adb5bd" stroke-width="1" stroke-dasharray="4 4"/>'
        f'<polyline points="{points}" fill="none" '
        f'stroke="{stroke}" stroke-width="1.5"/>'
        f'<text x="{pad_left:.1f}" y="{y_at(average) - 4:.1f}" '
        f'font-size="10" fill="#6c757d">{average_label}</text>'
        f'<text x="{pad_left:.1f}" y="{height - 4:.1f}" '
        f'font-size="10" fill="#6c757d">{hms(last_seconds)}</text>'
        f'</svg>'
    )


def heart_rate_svg(workout):
    """Render a heart-rate-over-time line graph as an inline SVG."""
    series = workout.get_heart_rate_series()
    if len(series) < 2:
        return ""
    bpm = [value for _, value in series]
    return mark_safe(
        _line_chart_svg(
            series,
            "#dc3545",
            "hr",
            f"avg {sum(bpm) / len(bpm):.0f}",
        )
    )


def pace_svg(workout):
    """Render a pace-over-time line graph as an inline SVG."""
    series = workout.get_pace_series()
    if len(series) < 2:
        return ""
    paces = [value for _, value in series]
    average = int(round(sum(paces) / len(paces)))
    return mark_safe(
        _line_chart_svg(
            series,
            "#198754",
            "pace",
            f"avg {hms(average)}/km",
            inverted=True,
        )
    )


def elevation_svg(workout):
    """Render an elevation-over-time line graph as an inline SVG."""
    series = workout.get_elevation_series()
    if len(series) < 2:
        return ""
    altitudes = [value for _, value in series]
    average = sum(altitudes) / len(altitudes)
    return mark_safe(
        _line_chart_svg(series, "#0d6efd", "elevation", f"avg {average:.0f} m")
    )


register = template.Library()
register.filter("emoji", emoji)
register.filter("hms", hms)
register.filter("status", status)
register.filter("heart_rate_svg", heart_rate_svg)
register.filter("pace_svg", pace_svg)
register.filter("elevation_svg", elevation_svg)
