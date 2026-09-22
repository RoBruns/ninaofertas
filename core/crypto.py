"""Criptografia autenticada para credenciais operacionais."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12
FINGERPRINT_BYTES = 16


def _read_key() -> bytes:
    encoded = os.getenv("CREDENTIALS_KEY")
    if not encoded:
        raise RuntimeError("CREDENTIALS_KEY não definida; credenciais não podem ser cifradas")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("CREDENTIALS_KEY deve ser base64 válido") from exc
    if len(key) != 32:
        raise RuntimeError("CREDENTIALS_KEY deve decodificar exatamente 32 bytes")
    return key


def _cipher() -> AESGCM:
    """Inicializa a cifra somente quando o subsistema de credenciais é usado."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(_read_key())


def encrypt(plaintext: str) -> bytes:
    """Cifra texto em UTF-8 e prefixa o nonce aleatório ao resultado."""
    nonce = os.urandom(NONCE_SIZE)
    return nonce + _cipher().encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt(ciphertext: bytes) -> str:
    """Autentica e decifra um valor produzido por :func:`encrypt`."""
    if len(ciphertext) <= NONCE_SIZE:
        raise ValueError("ciphertext inválido")
    nonce, payload = ciphertext[:NONCE_SIZE], ciphertext[NONCE_SIZE:]
    return _cipher().decrypt(nonce, payload, None).decode("utf-8")


def fingerprint(value: str) -> str:
    """Retorna os primeiros 16 bytes do SHA-256 em hexadecimal."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[: FINGERPRINT_BYTES * 2]
