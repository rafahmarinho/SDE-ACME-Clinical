"""Cryptographic helpers built only on vetted libraries (cryptography, hmac, hashlib, secrets).

* AES-256-GCM for field-level encryption of clinical free text (notes).
* HMAC-SHA256 for audit-log chaining, pseudonymisation and device key derivation.
"""

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_ENC_PREFIX = "v1:"


def _aes() -> AESGCM:
    return AESGCM(get_settings().key("data_encryption_key")[:32])


def encrypt_text(plaintext: str, context: str) -> str:
    """Encrypt with a random 96-bit nonce; `context` is bound as associated data."""
    nonce = secrets.token_bytes(12)
    ct = _aes().encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
    return _ENC_PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_text(token: str, context: str) -> str:
    if not token.startswith(_ENC_PREFIX):
        raise ValueError("Unsupported ciphertext version")
    raw = base64.b64decode(token[len(_ENC_PREFIX):])
    return _aes().decrypt(raw[:12], raw[12:], context.encode("utf-8")).decode("utf-8")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def audit_hash(prev_hash: str, record: dict[str, Any]) -> str:
    key = get_settings().key("audit_hmac_key")
    msg = (prev_hash + "|" + canonical_json(record)).encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def pseudonym(kind: str, identifier: str) -> str:
    """Stable, keyed pseudonym (not reversible without the key)."""
    key = get_settings().key("pseudonym_key")
    digest = hmac.new(key, f"{kind}:{identifier}".encode(), hashlib.sha256).hexdigest()
    return f"{kind.upper()[:2]}-{digest[:10].upper()}"


def device_secret(monitor_id: str) -> bytes:
    """Per-device signing secret derived from the master key (HKDF-like, single block)."""
    key = get_settings().key("device_master_key")
    return hmac.new(key, f"acme-device:{monitor_id}".encode(), hashlib.sha256).digest()


def sign_device_payload(monitor_id: str, timestamp: str, nonce: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + nonce.encode() + b"." + body
    return hmac.new(device_secret(monitor_id), msg, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_identifier(value: str) -> str:
    """Hash used for throttling keys so raw e-mail addresses are not stored in counters."""
    return hashlib.sha256(("throttle:" + value).encode()).hexdigest()
