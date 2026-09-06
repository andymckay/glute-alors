from django.core.exceptions import ObjectDoesNotExist


def site(request):
    user_profile = None
    if request.user.is_authenticated:
        try:
            user_profile = request.user.profile
        except ObjectDoesNotExist:
            user_profile = None
    return {
        "notification_count": (
            0
            if request.user.is_anonymous
            else request.user.notifications.filter(read=False).count()
        ),
        "user_profile": user_profile,
    }
