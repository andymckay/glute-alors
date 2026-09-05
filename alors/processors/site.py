def site(request):
    return {
        "notification_count": (
            0
            if request.user.is_anonymous
            else request.user.notifications.filter(read=False).count()
        )
    }
