from django.apps import AppConfig


class SalesConfig(AppConfig):
    name = "apps.sales"
    label = "sales"

    def ready(self):
        from apps.sales import signals  # noqa: F401
