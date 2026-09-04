from django.utils import timezone
import calendar
import datetime
from collections import defaultdict


def daily(date):
    date = datetime.datetime.strptime(date, "%Y-%m-%d")
    return {
        "start": date,
        "end": date,
        "next": (date + timezone.timedelta(days=1)).strftime("%Y-%m-%d"),
        "previous": (date - timezone.timedelta(days=1)).strftime("%Y-%m-%d"),
    }


def weekly(date):
    date = datetime.datetime.strptime(date, "%Y-%m-%d")
    start_of_week = date - timezone.timedelta(days=date.weekday())
    end_of_week = start_of_week + timezone.timedelta(days=6)
    return {
        "start": start_of_week,
        "end": end_of_week,
        "next": (start_of_week + timezone.timedelta(days=7)).strftime("%Y-%m-%d"),
        "previous": (start_of_week - timezone.timedelta(days=7)).strftime("%Y-%m-%d"),
    }


def monthly(date):
    date = datetime.datetime.strptime(date, "%Y-%m-%d")
    start_of_month = date.replace(day=1)
    end_day = calendar.monthrange(date.year, date.month)[1]
    return {
        "start": start_of_month,
        "end": date.replace(day=end_day),
        "next": (start_of_month + timezone.timedelta(days=32))
        .replace(day=1)
        .strftime("%Y-%m-%d"),
        "previous": (start_of_month - timezone.timedelta(days=1))
        .replace(day=1)
        .strftime("%Y-%m-%d"),
    }


def dateList(queryset):
    dates = defaultdict(list)
    for item in queryset:
        dates[item.get_date_as_str()].append(item)
    return dates

def combineDateLists(dates, **kwargs):
    result = []
    for date in dates:
        res = {"date": date}
        result.append(res)
        for (name, queryset) in kwargs.items():
            objects = queryset.get(date.strftime("%Y-%m-%d"))
            res[name] = objects
    return result