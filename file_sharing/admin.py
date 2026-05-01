from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html_join

from .models import SharedFile, FileShare, AccessLog, UserKey


class FileShareInline(admin.TabularInline):
    model = FileShare
    extra = 0
    fields = ('shared_with', 'shared_date', 'can_download', 'can_share', 'expiration_date')
    readonly_fields = ('shared_with', 'shared_date', 'can_download', 'can_share', 'expiration_date')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SharedFile)
class SharedFileAdmin(admin.ModelAdmin):
    list_display = (
        'original_filename',
        'encrypted_filename',
        'owner',
        'shared_with_users',
        'upload_date',
        'expiration_date',
        'download_count',
        'downloaded_by',
    )
    list_filter = ('upload_date', 'owner')
    search_fields = ('original_filename', 'owner__username', 'fileshare__shared_with__username')
    readonly_fields = ('downloaded_by',)
    inlines = (FileShareInline,)

    @admin.display(description='Shared with')
    def shared_with_users(self, obj):
        users = obj.fileshare_set.select_related('shared_with').order_by('shared_with__username')
        return ', '.join(share.shared_with.username for share in users) or '-'

    @admin.display(description='Downloaded by')
    def downloaded_by(self, obj):
        downloads = (
            AccessLog.objects
            .filter(file=obj, access_type='DOWNLOAD')
            .values('user__username')
            .annotate(total=Count('id'))
            .order_by('user__username')
        )

        if not downloads:
            return '-'

        return format_html_join(
            ', ',
            '<span>{}: {}</span>',
            ((download['user__username'], download['total']) for download in downloads)
        )

@admin.register(FileShare)
class FileShareAdmin(admin.ModelAdmin):
    list_display = ('shared_file', 'shared_by', 'shared_with', 'shared_date', 'can_download', 'can_share')
    list_filter = ('shared_date', 'can_download', 'can_share', 'shared_file__owner')
    search_fields = (
        'shared_file__original_filename',
        'shared_file__owner__username',
        'shared_with__username',
    )

    @admin.display(description='Shared by', ordering='shared_file__owner__username')
    def shared_by(self, obj):
        return obj.shared_file.owner

@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'file_display', 'access_type', 'access_date', 'ip_address')
    list_filter = ('access_type', 'access_date', 'user')
    search_fields = ('user__username', 'file__original_filename', 'file_name_snapshot')
    readonly_fields = ('user', 'file', 'access_type', 'access_date', 'ip_address', 'details')

    @admin.display(description='File', ordering='file__original_filename')
    def file_display(self, obj):
        if obj.file:
            return obj.file.original_filename
        return obj.file_name_snapshot or '-'

@admin.register(UserKey)
class UserKeyAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at')
    search_fields = ('user__username',)
