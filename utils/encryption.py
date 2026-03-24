from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import os

def encrypt_file(data, key):

    aesgcm = AESGCM(key)

    nonce = os.urandom(12)

    encrypted = aesgcm.encrypt(nonce, data, None)

    return "encrypted_file.enc", nonce + encrypted


CHUNK_SIZE = 64 * 1024  # 64KB


def encrypt_stream(file_obj, key):

    iv = os.urandom(16)

    cipher = Cipher(
        algorithms.AES(key),
        modes.CTR(iv)
    )

    encryptor = cipher.encryptor()

    encrypted_data = b""

    while True:
        chunk = file_obj.read(CHUNK_SIZE)

        if not chunk:
            break

        encrypted_chunk = encryptor.update(chunk)

        encrypted_data += encrypted_chunk

    encrypted_data += encryptor.finalize()

    return iv + encrypted_data