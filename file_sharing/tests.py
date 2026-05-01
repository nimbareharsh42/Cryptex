from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase

from .admin import FileShareAdmin, SharedFileAdmin
from .models import AccessLog, FileShare, SharedFile


class SharedFileAdminTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='test-pass')
        self.alice = User.objects.create_user(username='alice', password='test-pass')
        self.bob = User.objects.create_user(username='bob', password='test-pass')
        self.shared_file = SharedFile.objects.create(
            owner=self.owner,
            original_filename='report.pdf',
            encrypted_filename='encrypted/report.pdf',
            encryption_key=b'key',
        )
        self.shared_file_admin = SharedFileAdmin(SharedFile, admin.site)
        self.file_share_admin = FileShareAdmin(FileShare, admin.site)

    def test_file_share_admin_shows_who_shared_the_file(self):
        share = FileShare.objects.create(
            shared_file=self.shared_file,
            shared_with=self.alice,
        )

        self.assertEqual(self.file_share_admin.shared_by(share), self.owner)

    def test_shared_file_admin_shows_download_count_per_user(self):
        AccessLog.objects.create(
            user=self.alice,
            file=self.shared_file,
            access_type='DOWNLOAD',
        )
        AccessLog.objects.create(
            user=self.alice,
            file=self.shared_file,
            access_type='DOWNLOAD',
        )
        AccessLog.objects.create(
            user=self.bob,
            file=self.shared_file,
            access_type='DOWNLOAD',
        )
        AccessLog.objects.create(
            user=self.bob,
            file=self.shared_file,
            access_type='UPLOAD',
        )

        downloaded_by = str(self.shared_file_admin.downloaded_by(self.shared_file))

        self.assertIn('alice: 2', downloaded_by)
        self.assertIn('bob: 1', downloaded_by)
