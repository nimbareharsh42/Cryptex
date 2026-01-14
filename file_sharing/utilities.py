from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os

def generate_key_pair():
    # Generate RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
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
    public_key = serialization.load_pem_public_key(public_key_pem)
    encrypted = public_key.encrypt(
        data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return encrypted

def decrypt_with_private_key(encrypted_data, private_key_pem, password):
    private_key = serialization.load_pem_private_key(
        private_key_pem,
        password=password.encode() if password else None
    )
    decrypted = private_key.decrypt(
        encrypted_data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return decrypted

def encrypt_file(file, key):
    # Generate a Fernet key from our encryption key
    fernet_key = base64.urlsafe_b64encode(key)
    fernet = Fernet(fernet_key)
    
    # Read file data
    file_data = file.read()
    
    # Encrypt the data
    encrypted_data = fernet.encrypt(file_data)
    
    # Generate a unique filename
    filename = f"{os.urandom(16).hex()}.enc"
    
    return filename, encrypted_data

def decrypt_file(encrypted_data, key):
    # Generate a Fernet key from our encryption key
    fernet_key = base64.urlsafe_b64encode(key)
    fernet = Fernet(fernet_key)
    
    # Decrypt the data
    decrypted_data = fernet.decrypt(encrypted_data)
    
    return decrypted_data