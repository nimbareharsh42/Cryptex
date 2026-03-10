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
        ('DELETE', 'Delete'), 
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.ForeignKey(SharedFile, on_delete=models.CASCADE, null=True, blank=True)
    access_type = models.CharField(max_length=10, choices=ACCESS_TYPES)
    access_date = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.access_type} - {self.access_date}"
    

class Feedback(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    rating = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class UploadedFile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file_name = models.CharField(max_length=255)
    file_url = models.URLField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    download_count = models.IntegerField(default=0)
    file_size = models.IntegerField(null=True)

    class Meta:
        verbose_name = "Uploaded File"
        verbose_name_plural = "Uploaded Files"
    
    def __str__(self):
        return f"{self.file_name} - {self.user.username}"


class SharedFileRecord(models.Model):
    file = models.ForeignKey(UploadedFile, on_delete=models.CASCADE)
    shared_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files_shared_by_user')
    shared_with_email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)    
    
    class Meta:
        unique_together = ('file', 'shared_with_email')
        verbose_name = "Shared File Record"
        verbose_name_plural = "Shared File Records"
    
    def __str__(self):
        return f"{self.file.file_name} shared with {self.shared_with_email}"