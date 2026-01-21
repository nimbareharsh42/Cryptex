from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .models import SharedFile, FileShare, AccessLog, UserKey
from .utils import encrypt_file, decrypt_file, generate_key_pair, encrypt_with_public_key, decrypt_with_private_key, get_client_ip
from django.contrib.auth.models import User
from django.contrib import messages
import os
from django.conf import settings
from django.db import IntegrityError

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

    context = {
        'user_files': user_files,
        'shared_users': shared_users,
        'total_shares_count': shares.count(),
    }

    return render(request, 'file_sharing/dashboard.html', context)

@login_required
def upload_file(request):
    if request.method == 'POST' and request.FILES.get('file'):
        uploaded_file = request.FILES['file']
        
        # Show progress in UI (the actual progress is handled by JavaScript)
        # Generate encryption key
        encryption_key = os.urandom(32)
        
        # Encrypt the file
        encrypted_filename, encrypted_data = encrypt_file(uploaded_file, encryption_key)
        
        # Save encrypted file to disk
        file_path = os.path.join(settings.MEDIA_ROOT, 'encrypted_files', encrypted_filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)
        
        # Encrypt the encryption key with user's public key
        user_key = UserKey.objects.get(user=request.user)
        encrypted_key = encrypt_with_public_key(encryption_key, user_key.public_key)
        
        # Save file record to database
        shared_file = SharedFile(
            owner=request.user,
            original_filename=uploaded_file.name,
            encrypted_filename=encrypted_filename,
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
        
        return JsonResponse({'status': 'success'})
    
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
        file_path = os.path.join(settings.MEDIA_ROOT, 'encrypted_files', shared_file.encrypted_filename)
        if not os.path.exists(file_path):
            return HttpResponse("File not found", status=404)
            
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()
        
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
        print(f"Download error: {str(e)}")
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Error downloading file: {str(e)}", status=500)
    
    
@login_required
def share_file(request, file_id):
    shared_file = get_object_or_404(SharedFile, id=file_id, owner=request.user)

    if request.method == 'POST':
        username = request.POST.get('username')
        can_download = request.POST.get('can_download') == 'on'
        can_share = request.POST.get('can_share') == 'on'

        if not username:
            return HttpResponse("Username is required", status=400)

        try:
            user_to_share_with = User.objects.get(username=username)

            # Check if not sharing with yourself
            if user_to_share_with == request.user:
                return HttpResponse("You cannot share a file with yourself", status=400)

            # Validate if the file is already shared
            if FileShare.objects.filter(shared_file=shared_file, shared_with=user_to_share_with).exists():
                return HttpResponse("File is already shared with this user", status=400)

            # Get the receiver's public key
            receiver_key = UserKey.objects.get(user=user_to_share_with)

            # Decrypt the original encryption key using owner's private key
            owner_key = UserKey.objects.get(user=request.user)
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
                shared_with=user_to_share_with,
                can_download=can_download,
                can_share=can_share,
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

            return redirect('file_sharing:dashboard')

        except User.DoesNotExist:
            return HttpResponse("User not found", status=404)
        except UserKey.DoesNotExist:
            return HttpResponse("User does not have encryption keys", status=400)

    return render(request, 'file_sharing/share.html', {'file': shared_file})


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
            os.remove(file_path)

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
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create encryption keys for new user
            from .utils import create_user_keys
            create_user_keys(user)
            
            # Log the user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('file_sharing:dashboard')
    else:
        form = UserCreationForm()
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
def shared_with_me(request):
    shares = (
        FileShare.objects
        .filter(shared_with=request.user)
        .select_related('shared_file', 'shared_file__owner')
    )

    return render(request, 'file_sharing/shared_with_me.html', {
        'shared_files': shares  # Include details about the file owner
    })

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
    user_files = SharedFile.objects.filter(owner=request.user)

    if request.method == 'POST':
        file_id = request.POST.get('file_id')
        username = request.POST.get('username')

        shared_file = get_object_or_404(
            SharedFile,
            id=file_id,
            owner=request.user
        )

        try:
            recipient = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "User not found")
            return redirect('file_sharing:share_page')

        # Use get_or_create to prevent duplicate entries
        file_share, created = FileShare.objects.get_or_create(
            shared_file=shared_file,
            shared_with=recipient
        )

        if created:
            messages.success(request, "File shared successfully!")
        else:
            messages.info(request, "File has already been shared with this user.")

        return redirect('file_sharing:share_page')

    return render(request, 'file_sharing/share_page.html', {
        'user_files': user_files
    })

@login_required
def shared_history(request):
    # Files shared by the user
    shared_by_user = FileShare.objects.filter(
        shared_file__owner=request.user
    ).select_related('shared_with', 'shared_file')

    # Files received by the user
    received_by_user = FileShare.objects.filter(
        shared_with=request.user
    ).select_related('shared_file', 'shared_file__owner')

    # Debugging logs
    print("Shared by user:", shared_by_user)
    print("Received by user:", received_by_user)

    context = {
        'shared_by_user': shared_by_user,
        'received_by_user': received_by_user,
    }

    return render(request, 'file_sharing/shared_history.html', context)