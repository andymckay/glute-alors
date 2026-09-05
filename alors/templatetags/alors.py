from django import template
import time

emojis = {"run": "🏃‍♀", "walk": "🚶", "hike": "👢", "strength": "🏋", "recovery": "❤️"}


def emoji(value):
    return emojis.get(value.lower())


def hms(seconds):
    string = time.strftime("%H:%M:%S", time.gmtime(seconds))
    # Strip leading 0 and : if needed.
    if string.startswith("0"):
        return string[1:]
    if string.startswith("00:"):
        return string[3:]


def status(value):
    return {
        "missed": "danger",
        "under": "warning",
        "over": "warning",
        "done": "success",
    }.get(value.lower())


register = template.Library()
register.filter("emoji", emoji)
register.filter("hms", hms)
register.filter("status", status)
