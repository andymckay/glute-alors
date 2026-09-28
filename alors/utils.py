import calendar
import datetime
from collections import defaultdict
import pytz
from alors.models import UserProfile

def today(user):
    """
    Today for the user given their timezone
    """
    profile = UserProfile.objects.get(user=user)
    if not profile:
        timezone = 'UTC'
    else:
        timezone = pytz.timezone(profile.timezone)
    return datetime.datetime.utcnow().replace(tzinfo=timezone).date()

def dateList(queryset):
    dates = defaultdict(list)
    for item in queryset:
        try:
            # Labels have multiple dates, so instead return dates as a list.
            for date in item.get_dates_as_list():
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
        }
        result.append(res)
        for name, queryset in kwargs.items():
            objects = queryset.get(date.strftime("%Y-%m-%d"))
            res[name] = objects

    for res in result:
        # If we've got an actual run, don't show the planned.
        if res["actual"]:
            res["planned"] = None

    return result
