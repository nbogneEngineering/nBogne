"""
Encryption: L1 (End-to-End) and L2 (Transport)

L1: Encrypts the compressed payload. Only the destination adapter can decrypt.
    Applied at sending adapter, removed at receiving adapter. Mediator CANNOT read.

L2: Encrypts the entire wire packet for transport over GSM.
    Applied before SMS send, removed after SMS receive. Hop-by-hop.

Both use AES-256-GCM for authenticated encryption (confidentiality + integrity).
"""
import os
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_l1(plaintext: bytes, key_hex: str) -> bytes:
    """Encrypt with L1 (E2EE). Returns nonce + ciphertext."""
    key = bytes.fromhex(key_hex)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # 12 + len(plaintext) + 16 (tag)


def decrypt_l1(data: bytes, key_hex: str) -> bytes:
    """Decrypt L1. Input is nonce + ciphertext."""
    key = bytes.fromhex(key_hex)
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_l2(plaintext: bytes, key_hex: str) -> bytes:
    """Encrypt with L2 (transport). Returns nonce + ciphertext."""
    key = bytes.fromhex(key_hex)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_l2(data: bytes, key_hex: str) -> bytes:
    """Decrypt L2. Input is nonce + ciphertext."""
    key = bytes.fromhex(key_hex)
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encryption_overhead() -> int:
    """Returns the total overhead added by one layer of encryption.
    12 bytes nonce + 16 bytes GCM tag = 28 bytes per layer.
    Both layers: 56 bytes total overhead."""
    return 28  # per layer
