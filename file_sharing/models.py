from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from cryptography.fernet import Fernet
import base64
import os

class SharedFile(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    original_filename = models.CharField(max_length=255)
    encrypted_filename = models.CharField(max_length=255)
    encryption_key = models.BinaryField()  # Will be encrypted with user's public key
    upload_date = models.DateTimeField(default=timezone.now)
    expiration_date = models.DateTimeField(null=True, blank=True)
    download_count = models.IntegerField(default=0)
    
    def __str__(self):
        return self.original_filename

class FileShare(models.Model):
    shared_file = models.ForeignKey(SharedFile, on_delete=models.CASCADE)
    shared_with = models.ForeignKey(User, on_delete=models.CASCADE)
    shared_date = models.DateTimeField(default=timezone.now)
    can_download = models.BooleanField(default=True)
    can_share = models.BooleanField(default=False)
    expiration_date = models.DateTimeField(null=True, blank=True)
    encrypted_key = models.BinaryField(null=True, blank=True)  # Make it nullable first
    
    class Meta:
        unique_together = ('shared_file', 'shared_with')
    
    def __str__(self):
        return f"{self.shared_file.original_filename} shared with {self.shared_with.username}"

class UserKey(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    public_key = models.BinaryField()
    private_key_encrypted = models.BinaryField()  # Encrypted with user's password
    created_at = models.DateTimeField(default=timezone.now)


class AccessLog(models.Model):
    ACCESS_TYPES = (
        ('UPLOAD', 'Upload'),
        ('DOWNLOAD', 'Download'),
        ('SHARE', 'Share'),
        ('DELETE', 'Delete'),   # ✅ FIXED
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.ForeignKey(SharedFile, on_delete=models.CASCADE, null=True, blank=True)
    access_type = models.CharField(max_length=10, choices=ACCESS_TYPES)
    access_date = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.access_type} - {self.access_date}"