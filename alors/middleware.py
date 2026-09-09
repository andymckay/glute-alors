import pytz
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone


class UserTimezoneMiddleware:
    """Activate each logged-in user's chosen timezone for the request.

    Falls back to ``settings.TIME_ZONE`` for anonymous users and for users
    whose profile has not been created yet.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = settings.TIME_ZONE
        if request.user.is_authenticated:
            try:
                profile = request.user.profile
            except ObjectDoesNotExist:
                profile = None
            if profile is not None and profile.timezone:
                tzname = profile.timezone
        try:
            timezone.activate(pytz.timezone(tzname))
        except (pytz.UnknownTimeZoneError, ValueError):
            timezone.activate(pytz.timezone(settings.TIME_ZONE))
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
