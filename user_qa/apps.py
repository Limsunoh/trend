from django.apps import AppConfig


class QaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'user_qa'
    
    def ready(self):
        import user_qa.signals

