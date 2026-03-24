from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from .models import UserKey
import os
import base64
from cryptography.fernet import Fernet
from cryptography.exceptions import UnsupportedAlgorithm


def generate_key_pair():
    """
    Generate RSA key pair for public key cryptography
    """
    # Generate RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Serialize keys
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    return private_pem, public_pem

def encrypt_with_public_key(data, public_key_pem):
    """
    Encrypt data using RSA public key
    """
    public_key = serialization.load_pem_public_key(public_key_pem, backend=default_backend())
    encrypted = public_key.encrypt(
        data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return encrypted

def decrypt_with_private_key(encrypted_data, private_key_pem, password=None):
    """
    Decrypt data using RSA private key
    """
    try:
        # First try without password (for unencrypted private keys)
        try:
            private_key = serialization.load_pem_private_key(
                private_key_pem,
                password=None,
                backend=default_backend()
            )
        except (ValueError, TypeError, UnsupportedAlgorithm):
            # If that fails and password is provided, try with password
            if password:
                private_key = serialization.load_pem_private_key(
                    private_key_pem,
                    password=password.encode() if isinstance(password, str) else password,
                    backend=default_backend()
                )
            else:
                raise ValueError("Private key is encrypted but no password provided")
        
        # Decrypt the data
        decrypted_data = private_key.decrypt(
            encrypted_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        return decrypted_data
        
    except Exception as e:
        print(f"Error in decrypt_with_private_key: {str(e)}")
        raise e


CHUNK_SIZE = 64 * 1024  # 64KB




def decrypt_file(encrypted_data, encryption_key):
    fernet_key = base64.urlsafe_b64encode(encryption_key)
    cipher = Fernet(fernet_key)
    return cipher.decrypt(encrypted_data)


def get_client_ip(request):
    """
    Extract client IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def create_user_keys(user, password=None):
    """
    Create RSA key pair for a user
    """
    try:
        # Generate key pair
        private_key_pem, public_key_pem = generate_key_pair()
        
        user_key, created = UserKey.objects.get_or_create(
            user=user,
            defaults={
                'public_key': public_key_pem,
                'private_key_encrypted': private_key_pem,
            }
        )
        
        if not created:
            user_key.public_key = public_key_pem
            user_key.private_key_encrypted = private_key_pem
            user_key.save()
        
        return user_key
        
    except Exception as e:
        print(f"Error creating user keys: {str(e)}")
        raise

