"""Cryptographic primitives for ATHENA Protected Content.

No custom cryptographic primitive lives here. This module only provides a
small typed adapter around pyca/cryptography.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from athena.security.models import Argon2idParameters

AES_256_GCM = "AES-256-GCM"
ARGON2ID = "argon2id"
KEY_BYTES = 32
NONCE_BYTES = 12
SALT_BYTES = 16


class CryptoProviderError(RuntimeError):
    """Base error for Protected-Content crypto adapter failures."""


class CryptoUnavailableError(
    CryptoProviderError
):
    """Raised when the configured cryptographic primitive is unavailable."""


class CryptoAuthenticationError(
    CryptoProviderError
):
    """Raised on authenticated-decryption failure."""


@dataclass(frozen=True, slots=True)
class AeadEnvelope:
    nonce: bytes
    ciphertext: bytes


class CryptoProvider:
    """Thin adapter over Argon2id and AES-256-GCM."""

    def random_key(self) -> bytes:
        return secrets.token_bytes(
            KEY_BYTES
        )

    def random_nonce(self) -> bytes:
        return secrets.token_bytes(
            NONCE_BYTES
        )

    def random_salt(self) -> bytes:
        return secrets.token_bytes(
            SALT_BYTES
        )

    def derive_password_key(
        self,
        password: bytes,
        *,
        salt: bytes,
        parameters: Argon2idParameters,
    ) -> bytes:
        if not password:
            raise ValueError(
                "Protected-Content password "
                "must not be empty."
            )

        if len(salt) < SALT_BYTES:
            raise ValueError(
                "Argon2id salt must contain "
                "at least 16 bytes."
            )

        try:
            kdf = Argon2id(
                salt=salt,
                length=parameters.length,
                iterations=(
                    parameters.iterations
                ),
                lanes=parameters.lanes,
                memory_cost=(
                    parameters.memory_cost_kib
                ),
            )

            return kdf.derive(
                password
            )

        except UnsupportedAlgorithm as exc:
            raise CryptoUnavailableError(
                "Argon2id is unavailable in the active "
                "cryptography backend."
            ) from exc

        except MemoryError as exc:
            raise CryptoUnavailableError(
                "Insufficient memory for the configured "
                "Argon2id parameters."
            ) from exc

    def encrypt(
        self,
        key: bytes,
        plaintext: bytes,
        *,
        aad: bytes,
    ) -> AeadEnvelope:
        return self.encrypt_with_nonce(
            key,
            plaintext,
            nonce=self.random_nonce(),
            aad=aad,
        )

    def encrypt_with_nonce(
        self,
        key: bytes,
        plaintext: bytes,
        *,
        nonce: bytes,
        aad: bytes,
    ) -> AeadEnvelope:
        self._require_aes256_key(
            key
        )

        if len(nonce) != NONCE_BYTES:
            raise ValueError(
                "AES-256-GCM nonces must contain exactly 12 bytes."
            )

        ciphertext = AESGCM(
            key
        ).encrypt(
            nonce,
            plaintext,
            aad,
        )

        return AeadEnvelope(
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def decrypt(
        self,
        key: bytes,
        *,
        nonce: bytes,
        ciphertext: bytes,
        aad: bytes,
    ) -> bytes:
        self._require_aes256_key(
            key
        )

        if len(nonce) != NONCE_BYTES:
            raise CryptoAuthenticationError(
                "Protected-Content authentication failed."
            )

        try:
            return AESGCM(
                key
            ).decrypt(
                nonce,
                ciphertext,
                aad,
            )

        except InvalidTag as exc:
            raise CryptoAuthenticationError(
                "Protected-Content authentication failed."
            ) from exc

    @staticmethod
    def ciphertext_hash(
        ciphertext: bytes,
    ) -> bytes:
        return hashlib.sha256(
            ciphertext
        ).digest()

    @staticmethod
    def _require_aes256_key(
        key: bytes,
    ) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(
                "AES-256-GCM keys must contain "
                "exactly 32 bytes."
            )
