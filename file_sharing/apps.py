from django.apps import AppConfig

class FileSharingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'file_sharing'
    
    def ready(self):
        import file_sharing.signals