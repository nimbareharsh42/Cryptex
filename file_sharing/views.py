from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .models import SharedFile, FileShare, AccessLog, UserKey, UploadedFile, SharedFileRecord
from .utils import encrypt_file, decrypt_file, generate_key_pair, encrypt_with_public_key, decrypt_with_private_key, get_client_ip
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
import os
from django.conf import settings
from django.db import IntegrityError
from .models import Feedback
from utils.supabase_client import supabase
from .forms import CustomUserCreationForm
import uuid
from io import BytesIO
from urllib.parse import urlencode

def homepage(request):
    """Homepage for non-authenticated users"""
    if request.user.is_authenticated:
        return redirect('file_sharing:dashboard')
    return render(request, 'file_sharing/homepage.html')

@login_required
def dashboard(request):
    # Files uploaded by user
    user_files = SharedFile.objects.filter(owner=request.user)

    # Files YOU shared with others
    shares = FileShare.objects.filter(
        shared_file__owner=request.user
    ).select_related('shared_with', 'shared_file')

    # Group shares by user
    shared_users = {}
    for share in shares:
        user = share.shared_with
        if user not in shared_users:
            shared_users[user] = []
        shared_users[user].append(share)

    # Files shared WITH you
    received_files = FileShare.objects.filter(
        shared_with=request.user
    ).select_related('shared_file', 'shared_file__owner')

    context = {
        'user_files': user_files,
        'shared_users': shared_users,
        'received_files': received_files,
        'total_shares_count': shares.count(),
    }

    return render(request, 'file_sharing/dashboard.html', context)

@login_required
def upload_file(request):
    if request.method == 'POST' and request.FILES.get('file'):
        try:
            uploaded_file = request.FILES['file']

            # Limit file size to 50MB
            if uploaded_file.size > 50 * 1024 * 1024:
                return HttpResponse("File too large (max 50MB)", status=400)
            
            allowed_types = [
                "application/pdf",
                "application/zip",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "image/jpeg",
                "image/png",
                "video/mp4"
            ]

            if uploaded_file.content_type not in allowed_types:
                return HttpResponse("Unsupported file type", status=400)
            
            # Show progress in UI (the actual progress is handled by JavaScript)
            # Generate encryption key
            encryption_key = os.urandom(32)
            
            # Encrypt file
            encrypted_filename, encrypted_data = encrypt_file(uploaded_file, encryption_key)

            # Generate storage path
            storage_path = f"user_{request.user.id}/{uuid.uuid4().hex}_{encrypted_filename}"

            print("Uploading to Supabase:", storage_path)

            # Upload to Supabase
            try:
                supabase.storage.from_("encrypted-files").upload(
                    storage_path,
                    encrypted_data,
                    {"content-type": "application/octet-stream"}
                )
            except Exception as e:
                print("Supabase upload error:", str(e))
                import traceback
                traceback.print_exc()
                return HttpResponse(f"File storage failed: {str(e)}", status=500)

            # Encrypt the encryption key with user's public key
            user_key = UserKey.objects.get(user=request.user)
            encrypted_key = encrypt_with_public_key(encryption_key, user_key.public_key)
            
            # Save file record to database
            shared_file = SharedFile(
                owner=request.user,
                original_filename=uploaded_file.name,
                encrypted_filename=storage_path,
                encryption_key=encrypted_key
            )
            shared_file.save()
            
            # Log the upload
            AccessLog.objects.create(
                user=request.user,
                file=shared_file,
                access_type='UPLOAD',
                ip_address=get_client_ip(request),
                details=f'Uploaded file: {uploaded_file.name}'
            )
            
            # Return JSON for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'message': 'File uploaded successfully',
                    'file_id': shared_file.id,
                    'filename': uploaded_file.name
                })
            
            # Redirect for regular form submissions
            messages.success(request, f'File "{uploaded_file.name}" uploaded successfully!')
            return redirect('file_sharing:dashboard')
            
        except Exception as e:
            # Return JSON error for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=400)
            
            # Show error message for regular form submissions
            messages.error(request, f'Error uploading file: {str(e)}')
            return redirect('file_sharing:upload')
    
    return render(request, 'file_sharing/upload.html')

@login_required
def download_file(request, file_id):
    shared_file = get_object_or_404(SharedFile, id=file_id)
    
    try:
        # Check if user is the owner
        if shared_file.owner == request.user:
            # Owner downloading their own file
            user_key = UserKey.objects.get(user=request.user)
            encryption_key = decrypt_with_private_key(
                bytes(shared_file.encryption_key),
                user_key.private_key_encrypted,
                password=None
            )
        else:
            # Receiver downloading shared file
            share = get_object_or_404(FileShare, shared_file=shared_file, shared_with=request.user)

            # Check if share has expired
            if share.expiration_date and share.expiration_date < timezone.now():
                return HttpResponse("This share link has expired.", status=403)
            
            if not share.can_download:
                return HttpResponse("Permission denied", status=403)
            
            if share.encrypted_key:
                # New method: use the pre-encrypted key from FileShare
                user_key = UserKey.objects.get(user=request.user)
                encryption_key = decrypt_with_private_key(
                    bytes(share.encrypted_key),
                    user_key.private_key_encrypted,
                    password=None
                )
            else:
                # Fallback for existing shares: decrypt on-the-fly
                owner_key = UserKey.objects.get(user=shared_file.owner)
                encryption_key = decrypt_with_private_key(
                    bytes(shared_file.encryption_key),
                    owner_key.private_key_encrypted,
                    password=None
                )
        
        # Read encrypted file from disk
        print("Downloading from Supabase:", shared_file.encrypted_filename)
        file_path = shared_file.encrypted_filename

        response = supabase.storage.from_("encrypted-files").download(file_path)

        encrypted_data = response
        
        # Decrypt the file
        decrypted_data = decrypt_file(encrypted_data, encryption_key)
        
        # Update download count
        
        shared_file.download_count += 1
        shared_file.save()
        
        # Log the download
        AccessLog.objects.create(
            user=request.user,
            file=shared_file,
            access_type='DOWNLOAD',
            ip_address=get_client_ip(request),
            details=f'Downloaded file: {shared_file.original_filename}'
        )
        
        # Create response with decrypted file
        response = HttpResponse(decrypted_data, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{shared_file.original_filename}"'
        return response
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Download error: {str(e)}")
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Error downloading file: {str(e)}", status=500)
    
    
@login_required
def share_file(request, file_id):
    shared_file = get_object_or_404(SharedFile, id=file_id, owner=request.user)

    share_page_url = reverse('file_sharing:share_page')
    query_string = urlencode([('selected', shared_file.id)])
    return redirect(f'{share_page_url}?{query_string}')


@login_required
def audit_logs(request):
    # Exclude VIEW actions from the query
    logs = AccessLog.objects.filter(user=request.user).exclude(access_type='VIEW').order_by('-access_date')
    return render(request, 'file_sharing/audit_logs.html', {'logs': logs})

@login_required
def delete_file(request, file_id):
    if request.method == "POST":
        file = get_object_or_404(
            SharedFile,
            id=file_id,
            owner=request.user
        )

        filename = file.original_filename

        # delete encrypted file from disk
        file_path = os.path.join(
            settings.MEDIA_ROOT,
            "encrypted_files",
            file.encrypted_filename
        )

        if os.path.exists(file_path):
            supabase.storage.from_("encrypted-files").remove([file.encrypted_filename])

        # log delete action
        AccessLog.objects.create(
            user=request.user,
            file=file,
            access_type="DELETE",
            ip_address=get_client_ip(request),
            details=f"Deleted file: {filename}"
        )

        file.delete()

        return redirect(request.META.get("HTTP_REFERER", "file_sharing:dashboard"))

    return HttpResponse("Invalid request", status=400)

def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create encryption keys for new user
            from .utils import create_user_keys
            create_user_keys(user)
            
            # Log the user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('file_sharing:dashboard')
    else:
        form = CustomUserCreationForm()
    return render(request, 'file_sharing/register.html', {'form': form})

@login_required
def profile(request):
    user_files_count = SharedFile.objects.filter(owner=request.user).count()
    shared_files_count = FileShare.objects.filter(shared_file__owner=request.user).count()
    
    context = {
        'user_files_count': user_files_count,
        'shared_files_count': shared_files_count,
    }
    return render(request, 'file_sharing/profile.html', context)

@login_required
def user_uploads(request):
    user_files = SharedFile.objects.filter(owner=request.user).order_by('-upload_date')
    return render(request, 'file_sharing/user_uploads.html', {'user_files': user_files})

@login_required
def share_history(request):
    # Files shared by the user
    shared_by_user = FileShare.objects.filter(
        shared_file__owner=request.user
    ).select_related('shared_with', 'shared_file')

    # Files received by the user
    received_by_user = FileShare.objects.filter(
        shared_with=request.user
    ).select_related('shared_file', 'shared_file__owner')

    context = {
        'shared_by_user': shared_by_user,
        'received_by_user': received_by_user,
    }

    return render(request, 'file_sharing/share_history.html', context)

@login_required
def feedback(request):
    if request.method == 'POST':
        # Handle feedback submission
        feedback_text = request.POST.get('feedback')
        # Save feedback to database or send email
        return redirect('file_sharing:dashboard')
    
    return render(request, 'file_sharing/feedback.html')

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('file_sharing:dashboard')
        # If form is invalid, return to login with error
        return render(request, 'file_sharing/login.html', {'form': form, 'error': 'Invalid username or password'})
    else:
        form = AuthenticationForm()
    return render(request, 'file_sharing/login.html', {'form': form})

@login_required
def share_page(request):
    user_files = SharedFile.objects.filter(owner=request.user).order_by('-upload_date')
    requested_selected_file_ids = request.GET.getlist('selected')
    preselected_file_ids = [
        str(file_id)
        for file_id in user_files.filter(id__in=requested_selected_file_ids).values_list('id', flat=True)
    ]

    def build_share_page_url(selected_ids=None):
        share_page_url = reverse('file_sharing:share_page')
        normalized_selected_ids = [str(file_id) for file_id in (selected_ids or []) if str(file_id).strip()]
        if not normalized_selected_ids:
            return share_page_url
        return f"{share_page_url}?{urlencode([('selected', file_id) for file_id in normalized_selected_ids])}"

    if request.method == 'POST':
        file_ids = request.POST.getlist('file_ids')  # Get multiple file IDs
        username = request.POST.get('username')
        can_download = request.POST.get('can_download') == 'on'
        can_share = request.POST.get('can_share') == 'on'
        expiration_days = request.POST.get('expiration_days', '10')

        if not file_ids:
            messages.error(request, "Please select at least one file to share")
            return redirect(build_share_page_url())

        if not username:
            messages.error(request, "Please enter a recipient username")
            return redirect(build_share_page_url(file_ids))

        # Calculate expiration date
        expiration_date = None
        if expiration_days:
            try:
                days = int(expiration_days)
                if days > 0:
                    from datetime import timedelta
                    expiration_date = timezone.now() + timedelta(days=days)
            except ValueError:
                pass  # Invalid input, use None

        try:
            recipient = User.objects.get(username=username)
            
            # Check if not sharing with yourself
            if recipient == request.user:
                messages.error(request, "You cannot share files with yourself")
                return redirect(build_share_page_url(file_ids))

            # Process each selected file
            shared_count = 0
            already_shared_count = 0
            
            for file_id in file_ids:
                shared_file = get_object_or_404(
                    SharedFile,
                    id=file_id,
                    owner=request.user
                )

                # Check if already shared with this user
                if FileShare.objects.filter(shared_file=shared_file, shared_with=recipient).exists():
                    already_shared_count += 1
                    continue

                # Get keys for encryption
                receiver_key = UserKey.objects.get(user=recipient)
                owner_key = UserKey.objects.get(user=request.user)

                # Decrypt the original encryption key using owner's private key
                original_encryption_key = decrypt_with_private_key(
                    bytes(shared_file.encryption_key),
                    owner_key.private_key_encrypted,
                    password=None
                )

                # Re-encrypt the encryption key with receiver's public key
                re_encrypted_key = encrypt_with_public_key(
                    original_encryption_key,
                    receiver_key.public_key
                )

                # Create share record
                FileShare.objects.create(
                    shared_file=shared_file,
                    shared_with=recipient,
                    can_download=can_download,
                    can_share=can_share,
                    expiration_date=expiration_date,
                    encrypted_key=re_encrypted_key
                )

                # Log the share action
                AccessLog.objects.create(
                    user=request.user,
                    file=shared_file,
                    access_type='SHARE',
                    ip_address=get_client_ip(request),
                    details=f'Shared file with {username}'
                )

                shared_count += 1

            # Show appropriate message
            if shared_count > 0:
                if shared_count == 1:
                    messages.success(request, "File shared successfully!")
                else:
                    messages.success(request, f"{shared_count} files shared successfully!")
            
            if already_shared_count > 0:
                if already_shared_count == 1:
                    messages.info(request, "1 file was already shared with this user.")
                else:
                    messages.info(request, f"{already_shared_count} files were already shared with this user.")

        except User.DoesNotExist:
            messages.error(request, "User not found")
        except UserKey.DoesNotExist:
            messages.error(request, "User does not have encryption keys")
        except Exception as e:
            messages.error(request, f"Error sharing files: {str(e)}")

        return redirect(build_share_page_url(file_ids))

    return render(request, 'file_sharing/share_page.html', {
        'user_files': user_files,
        'preselected_file_ids': preselected_file_ids,
    })

def submit_feedback(request):
    if request.method == "POST":
        Feedback.objects.create(
            name=request.POST["name"],
            email=request.POST["email"],
            message=request.POST["message"],
            rating=request.POST["rating"]
        )
        return redirect("thank_you")

    return render(request, "feedback.html")

@login_required
def upload_file_supabase(request):
    """
    Upload file to Supabase Storage bucket 'userfiles'
    Validates file type and size (max 50MB)
    Supported: PDF, DOCX, ZIP, PPT/PPTX, images, videos
    """
    if request.method == "POST":
        try:
            # Check if file exists in request
            if 'file' not in request.FILES:
                messages.error(request, "No file was uploaded.")
                return redirect('file_sharing:upload_supabase')
            
            uploaded_file = request.FILES['file']
            
            # Validate file size (50MB = 50 * 1024 * 1024 bytes)
            MAX_FILE_SIZE = 50 * 1024 * 1024
            if uploaded_file.size > MAX_FILE_SIZE:
                messages.error(request, f"File size exceeds 50MB limit. Your file is {uploaded_file.size / (1024*1024):.2f}MB")
                return redirect('file_sharing:upload_supabase')
            
            # Validate file type
            ALLOWED_EXTENSIONS = [
                'pdf', 'docx', 'doc', 'zip', 'rar', '7z',
                'ppt', 'pptx', 'jpg', 'jpeg', 'png', 'gif', 'bmp',
                'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'
            ]
            file_extension = uploaded_file.name.split('.')[-1].lower()
            if file_extension not in ALLOWED_EXTENSIONS:
                messages.error(request, f"File type '.{file_extension}' is not supported.")
                return redirect('file_sharing:upload_supabase')
            
            # Generate unique file path to avoid collisions
            import uuid
            unique_filename = f"{request.user.id}_{uuid.uuid4().hex}_{uploaded_file.name}"
            file_path = f"uploads/{unique_filename}"
            
            # Upload to Supabase Storage
            file_data = uploaded_file.read()
            response = supabase.storage.from_("userfiles").upload(
                file_path,
                file_data,
                {"content-type": uploaded_file.content_type}
            )
            
            # Get public URL
            file_url = supabase.storage.from_("userfiles").get_public_url(file_path)
            
            # Save metadata to database
            UploadedFile.objects.create(
                user=request.user,
                file_name=uploaded_file.name,
                file_url=file_url
            )
            
            messages.success(request, f"File '{uploaded_file.name}' uploaded successfully!")
            return redirect('file_sharing:dashboard')
            
        except Exception as e:
            messages.error(request, f"Error uploading file: {str(e)}")
            return redirect('file_sharing:upload_supabase')
    
    return render(request, 'file_sharing/upload_supabase.html')


@login_required
def share_file_supabase(request):
    """
    Share uploaded files with other users by email
    """
    # Get user's uploaded files
    user_files = UploadedFile.objects.filter(user=request.user).order_by('-uploaded_at')
    
    if request.method == "POST":
        try:
            file_id = request.POST.get('file_id')
            recipient_email = request.POST.get('recipient_email')
            
            # Validate inputs
            if not file_id or not recipient_email:
                messages.error(request, "Please select a file and enter recipient email.")
                return redirect('file_sharing:share_supabase')
            
            # Get the file
            try:
                uploaded_file = UploadedFile.objects.get(id=file_id, user=request.user)
            except UploadedFile.DoesNotExist:
                messages.error(request, "File not found or you don't have permission.")
                return redirect('file_sharing:share_supabase')
            
            # Create share record (using get_or_create to avoid duplicates)
            shared_record, created = SharedFileRecord.objects.get_or_create(
                file=uploaded_file,
                shared_with_email=recipient_email,
                defaults={'shared_by': request.user}
            )
            
            if created:
                messages.success(request, f"File '{uploaded_file.file_name}' shared with {recipient_email}!")
            else:
                messages.info(request, f"File already shared with {recipient_email}.")
            
            return redirect('file_sharing:share_supabase')
            
        except Exception as e:
            messages.error(request, f"Error sharing file: {str(e)}")
            return redirect('file_sharing:share_supabase')
    
    # Get sharing history for the current user
    shared_files = SharedFileRecord.objects.filter(
        shared_by=request.user
    ).select_related('file').order_by('-created_at')
    
    context = {
        'user_files': user_files,
        'shared_files': shared_files,
    }
    
    return render(request, 'file_sharing/share_supabase.html', context)