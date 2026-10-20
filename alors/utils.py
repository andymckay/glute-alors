import calendar
import datetime
from collections import defaultdict
import pytz
from django.contrib.auth import get_user_model
from django.db.models import Q
from alors.models import UserProfile


def visible_users(user):
    """The users whose records the given user may see.

    A profile's visibility lists the people allowed to see its owner's rows, so
    this is the user plus everyone who has shared their profile with them.
    Superusers already see the whole site.
    """
    User = get_user_model()
    if not user or not user.is_authenticated:
        return User.objects.none()
    if user.is_superuser:
        return User.objects.all()
    return User.objects.filter(Q(pk=user.pk) | Q(profile__visibility=user)).distinct()


def today(user):
    """
    Today for the user given their timezone
    """
    try:
        profile = UserProfile.objects.get(user=user)
        timezone = pytz.timezone(profile.timezone)
    except UserProfile.DoesNotExist:
        timezone = pytz.timezone("America/Vancouver")
    return datetime.datetime.utcnow().replace(tzinfo=timezone).date()


def dateList(queryset, start=None, end=None):
    dates = defaultdict(list)
    for item in queryset:
        try:
            # Labels have multiple dates, so instead return dates as a list.
            for date in item.get_dates_as_list(start, end):
                dates[date].append(item)
        except AttributeError:
            dates[item.get_date_as_str()].append(item)
    return dates


def combineDateLists(dates, **kwargs):
    today = datetime.datetime.today().date()
    result = []
    for date in dates:
        res = {
            "date": date,
            "future": date > today,
            "past": date < today,
            "today": date == today,
            "weekday": date.weekday(),
        }
        result.append(res)
        for name, queryset in kwargs.items():
            objects = queryset.get(date.strftime("%Y-%m-%d"))
            res[name] = objects

    for res in result:
        # If we've got an actual run, don't show the planned.
        if res["actual"] and "run" in [a.workout_type for a in res["actual"]]:
            res["planned"] = None

    return result
