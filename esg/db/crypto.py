"""
Application-level field encryption for personal and deal-sensitive columns.

This is deliberately *not* a substitute for storage encryption — volume/TDE
encryption is an infrastructure control and is documented in
docs/DEPLOYMENT.md. What this adds is protection against the realistic
failure modes for a due-diligence tool: a leaked logical backup, a support
engineer with a read replica, or a stray SELECT in a log.

AES-256-GCM, random 96-bit nonce per write, key id stored alongside the
ciphertext so keys can be rotated without a full re-encrypt.

Ciphertext layout (base64 of):  key_id \x00 nonce(12) ciphertext+tag
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, TypeDecorator

from esg.config import settings

_NULL = b"\x00"


class KeyringError(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    pass


def _keyring():
    """{key_id: 32-byte key} parsed from ESG_DATA_KEYS."""
    raw = settings().data_keys_raw
    keys = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise KeyringError(f"Malformed ESG_DATA_KEYS entry (want key_id:base64): {item!r}")
        key_id, b64 = item.split(":", 1)
        try:
            key = base64.b64decode(b64, validate=True)
        except Exception as exc:
            raise KeyringError(f"Key {key_id!r} is not valid base64") from exc
        if len(key) != 32:
            raise KeyringError(f"Key {key_id!r} must be 32 bytes, got {len(key)}")
        keys[key_id.strip()] = key
    return keys


def active_key():
    keys = _keyring()
    if not keys:
        raise KeyringError(
            "No encryption keys configured. Set ESG_DATA_KEYS and ESG_ACTIVE_KEY_ID "
            "(generate with: python -m esg.db.crypto --generate)."
        )
    key_id = settings().active_key_id or next(iter(keys))
    if key_id not in keys:
        raise KeyringError(f"ESG_ACTIVE_KEY_ID={key_id!r} is not present in ESG_DATA_KEYS")
    return key_id, keys[key_id]


def encrypt(plaintext):
    if plaintext is None:
        return None
    key_id, key = active_key()
    nonce = os.urandom(12)
    blob = AESGCM(key).encrypt(nonce, str(plaintext).encode("utf-8"), key_id.encode())
    return base64.b64encode(key_id.encode() + _NULL + nonce + blob).decode("ascii")


def decrypt(stored):
    if stored is None:
        return None
    try:
        raw = base64.b64decode(stored, validate=True)
        key_id_bytes, rest = raw.split(_NULL, 1)
        nonce, blob = rest[:12], rest[12:]
    except Exception as exc:
        raise DecryptionError("Ciphertext is malformed") from exc

    key_id = key_id_bytes.decode()
    keys = _keyring()
    if key_id not in keys:
        raise DecryptionError(
            f"Ciphertext was written with key {key_id!r}, which is not in the keyring. "
            "Retired keys must stay in ESG_DATA_KEYS until the data is re-encrypted."
        )
    try:
        return AESGCM(keys[key_id]).decrypt(nonce, blob, key_id_bytes).decode("utf-8")
    except InvalidTag as exc:
        raise DecryptionError("Authentication failed — ciphertext or key is wrong") from exc


def key_id_of(stored):
    """Which key a stored value uses, for rotation reporting."""
    if stored is None:
        return None
    raw = base64.b64decode(stored, validate=True)
    return raw.split(_NULL, 1)[0].decode()


class Encrypted(TypeDecorator):
    """String column transparently encrypted at the application boundary.

    Values are opaque in the database, so these columns cannot be used for
    equality filters or ordering. Where lookup is needed (e.g. login by
    email) store a separate blind index — see models.UserAccount.email_hash.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)


def _main():
    import argparse

    parser = argparse.ArgumentParser(description="Field-encryption key utilities")
    parser.add_argument("--generate", action="store_true", help="print a new key")
    args = parser.parse_args()
    if args.generate:
        print(base64.b64encode(AESGCM.generate_key(bit_length=256)).decode())


if __name__ == "__main__":
    _main()
