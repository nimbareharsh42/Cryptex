from django.contrib import admin
from .models import SharedFile, FileShare, AccessLog, UserKey

@admin.register(SharedFile)
class SharedFileAdmin(admin.ModelAdmin):
    list_display = (
    'original_filename',
    'encrypted_filename',
    'owner',
    'upload_date',
    'expiration_date',
    'download_count'
    )
    list_filter = ('upload_date', 'owner')
    search_fields = ('original_filename', 'owner__username')

@admin.register(FileShare)
class FileShareAdmin(admin.ModelAdmin):
    list_display = ('shared_file', 'shared_with', 'shared_date', 'can_download', 'can_share')
    list_filter = ('shared_date', 'can_download', 'can_share')
    search_fields = ('shared_file__original_filename', 'shared_with__username')

@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'file', 'access_type', 'access_date', 'ip_address')
    list_filter = ('access_type', 'access_date')
    search_fields = ('user__username', 'file__original_filename')
    readonly_fields = ('user', 'file', 'access_type', 'access_date', 'ip_address', 'details')

@admin.register(UserKey)
class UserKeyAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at')
    search_fields = ('user__username',)