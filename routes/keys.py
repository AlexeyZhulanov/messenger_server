from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives import padding as symmetric_padding  # Для PKCS7
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding  # Для OAEP
from cryptography.hazmat.backends import default_backend
import base64


def load_master_key():
    with open('/etc/secrets/master_key', 'rb') as f:
        return f.read()
    

def load_symmetric_key():
    with open('/etc/secrets/symmetric_key', 'rb') as f:
        return f.read()


def decrypt_key(master_key_b64, encrypted_key_b64):
    # Декодируем мастер-ключ и зашифрованный ключ
    master_key = base64.b64decode(master_key_b64)
    encrypted_key = base64.b64decode(encrypted_key_b64)

    # Извлекаем IV и зашифрованный ключ
    iv = encrypted_key[:16]
    encrypted_key = encrypted_key[16:]

    # Расшифровываем ключ
    cipher = Cipher(algorithms.AES(master_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_key_padded = decryptor.update(encrypted_key) + decryptor.finalize()

    # Убираем PKCS7 padding
    unpadder = symmetric_padding.PKCS7(128).unpadder()
    decrypted_key = unpadder.update(decrypted_key_padded) + unpadder.finalize()

    return decrypted_key


def encrypt_with_public_key(symmetric_key, public_key_der_b64):
    # Декодируем Base64
    public_key_der = base64.b64decode(public_key_der_b64)

    # Загружаем публичный ключ из DER
    public_key = serialization.load_der_public_key(
        public_key_der,
        backend=default_backend()
    )

    encrypted_key = public_key.encrypt(
        symmetric_key,
        asymmetric_padding.OAEP(
            mgf=asymmetric_padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    
    # Кодируем зашифрованный ключ в Base64
    encrypted_key_b64 = base64.b64encode(encrypted_key).decode('utf-8')
    return encrypted_key_b64


# Основная функция
def encrypt_symmetric_key_for_user(public_key_der_b64):
    # Загружаем мастер-ключ и симметричный ключ
    master_key = load_master_key()
    encrypted_symmetric_key = load_symmetric_key()

    # Расшифровываем симметричный ключ
    symmetric_key = decrypt_key(master_key, encrypted_symmetric_key)

    # Шифруем симметричный ключ публичным ключом пользователя
    encrypted_key_for_user = encrypt_with_public_key(symmetric_key, public_key_der_b64)

    return encrypted_key_for_user
