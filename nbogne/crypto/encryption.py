"""
Encryption: L1 (End-to-End) and L2 (Transport)

L1: Encrypts the compressed payload. Only the destination adapter can decrypt.
    Applied at sending adapter, removed at receiving adapter. Mediator CANNOT read.
    Nonce is derived from msg_id (available in wire header), NOT stored in output.

L2: Encrypts the entire wire packet for transport over GSM.
    Applied before SMS send, removed after SMS receive. Hop-by-hop.
    Random nonce prepended to output (msg_id not available before L2 decryption).

Both use AES-256-GCM for authenticated encryption (confidentiality + integrity).
"""
import os
import struct
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _derive_l1_nonce(msg_id: bytes) -> bytes:
    """Derive a 12-byte GCM nonce from msg_id for L1 encryption.
    Uses HMAC-like derivation for uniform distribution.
    NOTE: msg_id is 4 bytes (random). Nonce collision risk at ~65K messages
    per key. For production, extend msg_id to 8+ bytes."""
    # Domain-separated: hash msg_id with a fixed label to get 12 bytes
    h = hashlib.sha256(b"nBogne-L1-nonce:" + msg_id).digest()
    return h[:12]


def encrypt_l1(plaintext: bytes, key_hex: str, msg_id: bytes) -> bytes:
    """Encrypt with L1 (E2EE). Nonce derived from msg_id — NOT stored in output.
    Returns ciphertext + tag only (saves 12 bytes vs random nonce)."""
    key = bytes.fromhex(key_hex)
    nonce = _derive_l1_nonce(msg_id)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return ciphertext  # len(plaintext) + 16 (tag), NO nonce


def decrypt_l1(data: bytes, key_hex: str, msg_id: bytes) -> bytes:
    """Decrypt L1. Nonce derived from msg_id. Input is ciphertext + tag."""
    key = bytes.fromhex(key_hex)
    nonce = _derive_l1_nonce(msg_id)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, data, None)


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
    """Returns the total overhead added by both encryption layers.
    L1: 16 bytes (GCM tag only, nonce derived from msg_id).
    L2: 28 bytes (12 nonce + 16 GCM tag).
    Total: 44 bytes (down from 56)."""
    return 44
