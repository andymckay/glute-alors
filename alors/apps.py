from django.apps import AppConfig


class BaseConfig(AppConfig):
    name = "alors"

    def ready(self):
        from . import signals  # noqa: F401
