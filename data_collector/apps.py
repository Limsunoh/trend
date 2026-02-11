from django.apps import AppConfig


class DataCollectorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "data_collector"

    def ready(self):
        import data_collector.signals  # noqa: F401
