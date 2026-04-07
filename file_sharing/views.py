from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.models import User
from django.urls import reverse
from urllib.parse import urlencode
from decouple import config
from .forms import CustomUserCreationForm
from jose import jwt
from django.views.decorators.csrf import csrf_exempt


from .models import SharedFile, FileShare, AccessLog, UserKey, Feedback
from .utils import (
    encrypt_with_public_key,
    decrypt_with_private_key,
    get_client_ip
)
from .services.supabase_service import (
    upload_file_to_storage,
    download_file_from_storage,
    delete_file
)

import os
import uuid
import base64
from cryptography.fernet import Fernet


def homepage(request):
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

            # File size limit
            if uploaded_file.size > 10 * 1024 * 1024:
                return HttpResponse("File too large (max 10MB)", status=400)

            filename = uploaded_file.name.lower()

            # Allowed types
            allowed_extensions = (
                '.pdf', '.zip',
                '.docx', '.xlsx', '.pptx',
                '.jpg', '.jpeg', '.png',
                '.mp4'
            )

            if not filename.endswith(allowed_extensions):
                return HttpResponse("Unsupported file type", status=400)

            # Get user key
            user_key = UserKey.objects.get(user=request.user)

            # Encrypt file
            file_data = uploaded_file.read()
            encryption_key = os.urandom(32)

            fernet_key = base64.urlsafe_b64encode(encryption_key)
            cipher = Fernet(fernet_key)
            encrypted_data = cipher.encrypt(file_data)

            filename = os.path.basename(uploaded_file.name)
            storage_path = f"user_{request.user.id}/{uuid.uuid4().hex}_{filename}"

            # Upload to Supabase
            response = upload_file_to_storage(storage_path, encrypted_data)

            if not response:
                return HttpResponse("Upload failed", status=500)

            # Save DB
            with transaction.atomic():
                shared_file = SharedFile.objects.create(
                    owner=request.user,
                    original_filename=filename,
                    encrypted_filename=storage_path,
                    encryption_key=encrypt_with_public_key(
                        encryption_key,
                        user_key.public_key
                    )
                )

                AccessLog.objects.create(
                    user=request.user,
                    file=shared_file,
                    file_name_snapshot=shared_file.original_filename,
                    file_id_snapshot=shared_file.id,
                    access_type='UPLOAD',
                    ip_address=get_client_ip(request),
                    details=f'Uploaded file: {filename}'
                )

            messages.success(request, f'File "{filename}" uploaded successfully!')
            return redirect('file_sharing:dashboard')

        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('file_sharing:upload')

    return render(request, 'file_sharing/upload.html')


@login_required
def download_file(request, file_id):
    shared_file = get_object_or_404(SharedFile, id=file_id)

    try:
        if shared_file.owner == request.user:
            user_key = UserKey.objects.get(user=request.user)
            encrypted_key = shared_file.encryption_key
        else:
            share = get_object_or_404(
                FileShare,
                shared_file=shared_file,
                shared_with=request.user
            )

            if share.expiration_date and share.expiration_date < timezone.now():
                return HttpResponse("Expired link", status=403)

            if not share.can_download:
                return HttpResponse("Permission denied", status=403)

            user_key = UserKey.objects.get(user=request.user)
            encrypted_key = share.encrypted_key or shared_file.encryption_key

        # Normalize key
        if isinstance(encrypted_key, memoryview):
            encrypted_key = encrypted_key.tobytes()
        elif isinstance(encrypted_key, str):
            encrypted_key = encrypted_key.encode()

        encryption_key = decrypt_with_private_key(
            encrypted_key,
            user_key.private_key_encrypted
        )

        # Download from Supabase
        encrypted_data = download_file_from_storage(shared_file.encrypted_filename)

        # Normalize file data
        if isinstance(encrypted_data, memoryview):
            encrypted_data = encrypted_data.tobytes()
        elif hasattr(encrypted_data, "read"):
            encrypted_data = encrypted_data.read()
        else:
            encrypted_data = bytes(encrypted_data)

        # Decrypt
        fernet_key = base64.urlsafe_b64encode(encryption_key)
        decrypted_data = Fernet(fernet_key).decrypt(encrypted_data)

        # Log
        shared_file.download_count += 1
        shared_file.save()

        AccessLog.objects.create(
            user=request.user,
            file=shared_file,
            file_name_snapshot=shared_file.original_filename,
            file_id_snapshot=shared_file.id,
            access_type='DOWNLOAD',
            ip_address=get_client_ip(request),
            details=f'Downloaded file: {shared_file.original_filename}'
        )

        response = HttpResponse(decrypted_data, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{shared_file.original_filename}"'
        return response

    except Exception as e:
        return HttpResponse(f"Download error: {str(e)}", status=500)
    
    
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
def delete_file_view(request, file_id):
    if request.method == "POST":
        file = get_object_or_404(SharedFile, id=file_id, owner=request.user)

        # Delete from Supabase
        delete_file(file.encrypted_filename)

        AccessLog.objects.create(
            user=request.user,
            file=file,
            file_name_snapshot=file.original_filename,
            file_id_snapshot=file.id,
            access_type="DELETE",
            ip_address=get_client_ip(request),
            details=f"Deleted file: {file.original_filename}"
        )

        file.delete()
        return redirect('file_sharing:dashboard')

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
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'You cannot share files with yourself'}, status=400)
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
                    file_name_snapshot=shared_file.original_filename,
                    file_id_snapshot=shared_file.id,
                    access_type='SHARE',
                    ip_address=get_client_ip(request),
                    details=f'Shared file {shared_file.original_filename} with {username}'
                )

                shared_count += 1

            # Show appropriate message
            if shared_count > 0 or already_shared_count > 0:
                pass  # Messages handled by AJAX response or redirect below

        except User.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
            messages.error(request, "User not found")
        except UserKey.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'User does not have encryption keys'}, status=400)
            messages.error(request, "User does not have encryption keys")
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': f'Error sharing files: {str(e)}'}, status=500)
            messages.error(request, f"Error sharing files: {str(e)}")
        else:
            # Return JSON for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'shared_count': shared_count,
                    'already_shared_count': already_shared_count,
                    'recipient': username,
                })

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


User = get_user_model()

SUPABASE_JWT_SECRET = "SUPABASE_JWT_SECRET"


@csrf_exempt
def supabase_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    jwt_secret = config("SUPABASE_JWT_SECRET", default="")
    if not jwt_secret or jwt_secret == "SUPABASE_JWT_SECRET":
        return JsonResponse({"error": "SUPABASE_JWT_SECRET is not configured"}, status=500)

    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return JsonResponse({"error": "No token"}, status=401)

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return JsonResponse({"error": "Invalid authorization header format"}, status=401)

    token = parts[1]

    try:
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except Exception:
        return JsonResponse({"error": "Invalid token"}, status=401)

    email = payload.get("email")
    if not email:
        return JsonResponse({"error": "Token does not contain email"}, status=400)

    user = User.objects.filter(email=email).first()
    created = False

    if not user:
        base_username = (email.split("@")[0] or "google_user").replace(" ", "_")[:30]
        candidate = base_username
        suffix = 1

        while User.objects.filter(username=candidate).exists():
            suffix_str = f"_{suffix}"
            candidate = f"{base_username[:max(1, 30 - len(suffix_str))]}{suffix_str}"
            suffix += 1

        user = User.objects.create_user(username=candidate, email=email)
        created = True

    if created:
        from .utils import create_user_keys
        create_user_keys(user)

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    return JsonResponse({"status": "logged in"})