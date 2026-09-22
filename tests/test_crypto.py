from __future__ import annotations

import base64
import os

import pytest

pytest.importorskip("cryptography", reason="cryptography não instalada")

from cryptography.exceptions import InvalidTag

from core.crypto import decrypt, encrypt, fingerprint


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def test_round_trip_e_nonce_unico(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIALS_KEY", _key())
    first = encrypt("segredo operacional")
    second = encrypt("segredo operacional")

    assert decrypt(first) == "segredo operacional"
    assert first != second
    assert first[:12] != second[:12]


def test_chave_errada_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIALS_KEY", _key())
    ciphertext = encrypt("segredo")
    monkeypatch.setenv("CREDENTIALS_KEY", _key())

    with pytest.raises(InvalidTag):
        decrypt(ciphertext)


def test_sem_chave_falha_alto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDENTIALS_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CREDENTIALS_KEY"):
        encrypt("segredo")


def test_fingerprint_estavel_e_truncado() -> None:
    assert fingerprint("valor") == fingerprint("valor")
    assert fingerprint("valor") != fingerprint("outro")
    assert len(fingerprint("valor")) == 32
