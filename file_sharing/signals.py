from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserKey
from .utils import generate_key_pair

@receiver(post_save, sender=User)
def create_user_keys(sender, instance, created, **kwargs):
    if created:
        # Generate key pair for new user
        private_key, public_key = generate_key_pair()
        
        # Store keys
        UserKey.objects.create(
            user=instance,
            public_key=public_key,
            private_key_encrypted=private_key
        )