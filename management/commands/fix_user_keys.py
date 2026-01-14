from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from file_sharing.models import UserKey
from file_sharing.utils import generate_key_pair
import os

class Command(BaseCommand):
    help = 'Fix existing user keys that are not properly encrypted'
    
    def handle(self, *args, **options):
        users_with_keys = User.objects.filter(userkey__isnull=False)
        
        for user in users_with_keys:
            try:
                user_key = UserKey.objects.get(user=user)
                self.stdout.write(f"Checking keys for user: {user.username}")
                
                # Try to regenerate keys with proper encryption
                public_key_pem, private_key_pem = generate_key_pair(None)  # No password
                
                user_key.public_key = public_key_pem
                user_key.private_key_encrypted = private_key_pem
                user_key.save()
                
                self.stdout.write(
                    self.style.SUCCESS(f"Fixed keys for user: {user.username}")
                )
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error fixing keys for {user.username}: {str(e)}")
                )   