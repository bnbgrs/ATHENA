"""Runtime lock/unlock and envelope encryption for ATHENA Protected Content."""

from __future__ import annotations

import hmac
import json
import uuid
from dataclasses import dataclass

from athena.common.ids import new_uuid7
from athena.common.time import utc_now_us
from athena.security.crypto import (
    AES_256_GCM,
    ARGON2ID,
    KEY_BYTES,
    CryptoAuthenticationError,
    CryptoProvider,
)
from athena.security.models import (
    DEFAULT_ARGON2ID_PARAMETERS,
    Argon2idParameters,
    KeySlotType,
    KeyStatus,
    PasswordKeySlotRecord,
    ProtectedBlobEnvelopeRecord,
    ProtectedPayloadRecord,
    ProtectionScopeKeyRecord,
    ProtectionScopeLifecycle,
    ProtectionScopeRecord,
    SecurityContext,
)
from athena.security.repository import (
    ProtectionInitializationConflictError,
    ProtectionRepository,
)

_AAD_VERSION = 1


class ProtectedContentError(
    RuntimeError
):
    """Base runtime error for ATHENA Protected Content."""


class ProtectedContentNotInitializedError(
    ProtectedContentError
):
    """Raised before a password Root-Key slot has been initialized."""


class ProtectedContentAlreadyInitializedError(
    ProtectedContentError
):
    """Raised when initialization is attempted more than once."""


class ProtectedContentUnlockError(
    ProtectedContentError
):
    """Generic fail-closed unlock error without internal key-detail leakage."""


class ProtectionScopeLockedError(
    ProtectedContentError
):
    """Raised when protected bytes are requested without an unlocked scope."""


class ProtectionScopeUnavailableError(
    ProtectedContentError
):
    """Raised when a non-active scope is used."""


class ProtectedContentIntegrityError(
    ProtectedContentError
):
    """Raised when authenticated Protected-Content state cannot be trusted."""


@dataclass(slots=True)
class _UnlockedScopeKey:
    scope_key_id: uuid.UUID
    key: bytearray


class ProtectedContentService:
    """Runtime-only unlock state plus envelope-encrypted structured payloads."""

    name = "protected-content"

    def __init__(
        self,
        *,
        repository: ProtectionRepository,
        crypto: CryptoProvider,
    ) -> None:
        self.repository = repository
        self.crypto = crypto
        self._unlocked_scope_keys: dict[
            uuid.UUID,
            _UnlockedScopeKey,
        ] = {}

    def start(self) -> None:
        # Never carry unlocked state across
        # a Core lifecycle transition.
        self.lock_all()

    def stop(self) -> None:
        self.lock_all()

    @property
    def context(
        self,
    ) -> SecurityContext:
        return SecurityContext(
            unlocked_protection_scopes=(
                frozenset(
                    self._unlocked_scope_keys
                )
            )
        )

    @property
    def initialized(
        self,
    ) -> bool:
        return (
            self.repository.active_password_slot()
            is not None
        )

    def initialize_password(
        self,
        password: bytes,
        *,
        parameters: Argon2idParameters = (
            DEFAULT_ARGON2ID_PARAMETERS
        ),
    ) -> PasswordKeySlotRecord:
        if self.repository.has_any_key_slots():
            raise (
                ProtectedContentAlreadyInitializedError(
                    "ATHENA Protected Content "
                    "is already initialized."
                )
            )

        key_slot_id = new_uuid7()
        created_at_us = utc_now_us()
        salt = self.crypto.random_salt()

        kek = bytearray(
            self.crypto.derive_password_key(
                password,
                salt=salt,
                parameters=parameters,
            )
        )

        root_key = bytearray()

        try:
            root_key.extend(
                self.crypto.random_key()
            )

            aad = _key_slot_aad(
                key_slot_id=key_slot_id,
                parameters=parameters,
                salt=salt,
            )

            wrapped = self.crypto.encrypt(
                bytes(kek),
                bytes(root_key),
                aad=aad,
            )

            record = PasswordKeySlotRecord(
                key_slot_id=key_slot_id,
                slot_type=(
                    KeySlotType.PASSWORD
                ),
                kdf_algorithm=ARGON2ID,
                kdf_parameters=parameters,
                salt=salt,
                wrap_algorithm=AES_256_GCM,
                wrap_nonce=wrapped.nonce,
                wrapped_root_key=(
                    wrapped.ciphertext
                ),
                created_at_us=created_at_us,
                retired_at_us=None,
                status=KeyStatus.ACTIVE,
            )

            try:
                (
                    self.repository
                    .create_initial_password_slot(
                        record
                    )
                )

            except (
                ProtectionInitializationConflictError
            ) as exc:
                raise (
                    ProtectedContentAlreadyInitializedError(
                        "ATHENA Protected Content "
                        "is already initialized."
                    )
                ) from exc

            return record

        finally:
            _wipe(
                root_key
            )
            _wipe(
                kek
            )

    def create_scope(
        self,
        password: bytes,
        *,
        neutral_label: str | None = None,
    ) -> ProtectionScopeRecord:
        label = _normalize_neutral_label(
            neutral_label
        )

        root_key = self._unwrap_root_key(
            password
        )

        scope_key = bytearray(
            self.crypto.random_key()
        )

        protection_scope_id = new_uuid7()
        scope_key_id = new_uuid7()
        created_at_us = utc_now_us()
        key_version = 1

        try:
            aad = _scope_key_aad(
                protection_scope_id=(
                    protection_scope_id
                ),
                scope_key_id=scope_key_id,
                key_version=key_version,
            )

            wrapped = self.crypto.encrypt(
                bytes(root_key),
                bytes(scope_key),
                aad=aad,
            )

            scope = ProtectionScopeRecord(
                protection_scope_id=(
                    protection_scope_id
                ),
                lifecycle_state=(
                    ProtectionScopeLifecycle.ACTIVE
                ),
                created_at_us=created_at_us,
                current_scope_key_id=(
                    scope_key_id
                ),
                neutral_label=label,
            )

            key_record = (
                ProtectionScopeKeyRecord(
                    scope_key_id=scope_key_id,
                    protection_scope_id=(
                        protection_scope_id
                    ),
                    key_version=key_version,
                    wrap_algorithm=(
                        AES_256_GCM
                    ),
                    wrap_nonce=wrapped.nonce,
                    wrapped_scope_key=(
                        wrapped.ciphertext
                    ),
                    created_at_us=(
                        created_at_us
                    ),
                    retired_at_us=None,
                    status=KeyStatus.ACTIVE,
                )
            )

            (
                self.repository
                .create_scope_with_key(
                    scope,
                    key_record,
                )
            )

            return scope

        finally:
            _wipe(
                scope_key
            )
            _wipe(
                root_key
            )

    def unlock_scope(
        self,
        protection_scope_id: uuid.UUID,
        password: bytes,
    ) -> SecurityContext:
        scope = self.repository.get_scope(
            protection_scope_id
        )

        if (
            scope.lifecycle_state
            is not ProtectionScopeLifecycle.ACTIVE
        ):
            raise (
                ProtectionScopeUnavailableError(
                    "ProtectionScope is not active."
                )
            )

        scope_key_record = (
            self.repository
            .get_current_scope_key(
                protection_scope_id
            )
        )

        root_key = self._unwrap_root_key(
            password
        )

        try:
            if (
                scope_key_record.wrap_algorithm
                != AES_256_GCM
            ):
                raise (
                    ProtectedContentIntegrityError(
                        "ProtectionScope key wrapping "
                        "algorithm is unsupported."
                    )
                )

            try:
                scope_key = bytearray(
                    self.crypto.decrypt(
                        bytes(root_key),
                        nonce=(
                            scope_key_record
                            .wrap_nonce
                        ),
                        ciphertext=(
                            scope_key_record
                            .wrapped_scope_key
                        ),
                        aad=_scope_key_aad(
                            protection_scope_id=(
                                protection_scope_id
                            ),
                            scope_key_id=(
                                scope_key_record
                                .scope_key_id
                            ),
                            key_version=(
                                scope_key_record
                                .key_version
                            ),
                        ),
                    )
                )

            except (
                CryptoAuthenticationError
            ) as exc:
                raise (
                    ProtectedContentIntegrityError(
                        "Protected scope key "
                        "authentication failed."
                    )
                ) from exc

            try:
                if len(scope_key) != KEY_BYTES:
                    raise (
                        ProtectedContentIntegrityError(
                            "Protected scope key has "
                            "an invalid length."
                        )
                    )

                previous = (
                    self._unlocked_scope_keys.pop(
                        protection_scope_id,
                        None,
                    )
                )

                if previous is not None:
                    _wipe(
                        previous.key
                    )

                self._unlocked_scope_keys[
                    protection_scope_id
                ] = _UnlockedScopeKey(
                    scope_key_id=(
                        scope_key_record.scope_key_id
                    ),
                    key=bytearray(
                        scope_key
                    ),
                )

                return self.context

            finally:
                _wipe(
                    scope_key
                )

        finally:
            _wipe(
                root_key
            )

    def lock_scope(
        self,
        protection_scope_id: uuid.UUID,
    ) -> SecurityContext:
        unlocked = (
            self._unlocked_scope_keys.pop(
                protection_scope_id,
                None,
            )
        )

        if unlocked is not None:
            _wipe(
                unlocked.key
            )

        return self.context

    def lock_all(
        self,
    ) -> SecurityContext:
        for unlocked in (
            self._unlocked_scope_keys.values()
        ):
            _wipe(
                unlocked.key
            )

        self._unlocked_scope_keys.clear()

        return self.context

    def is_unlocked(
        self,
        protection_scope_id: uuid.UUID,
    ) -> bool:
        return (
            protection_scope_id
            in self._unlocked_scope_keys
        )

    def store_payload(
        self,
        protection_scope_id: uuid.UUID,
        plaintext: bytes,
    ) -> ProtectedPayloadRecord:
        record = self.prepare_payload(
            protection_scope_id,
            plaintext,
        )

        self.repository.insert_payload(
            record
        )

        return record

    def prepare_payload(
        self,
        protection_scope_id: uuid.UUID,
        plaintext: bytes,
    ) -> ProtectedPayloadRecord:
        """Encrypt one payload without persisting it."""
        if not plaintext:
            raise ValueError(
                "Protected payload must not be empty."
            )

        unlocked = self._require_unlocked(
            protection_scope_id
        )

        current_key = (
            self.repository
            .get_current_scope_key(
                protection_scope_id
            )
        )

        if (
            current_key.scope_key_id
            != unlocked.scope_key_id
            or current_key.status
            is not KeyStatus.ACTIVE
        ):
            raise ProtectionScopeLockedError(
                "ProtectionScope key changed; "
                "unlock the scope again."
            )

        payload_id = new_uuid7()
        created_at_us = utc_now_us()

        dek = bytearray(
            self.crypto.random_key()
        )

        try:
            wrapped_dek = self.crypto.encrypt(
                bytes(
                    unlocked.key
                ),
                bytes(
                    dek
                ),
                aad=_payload_dek_aad(
                    protected_payload_id=(
                        payload_id
                    ),
                    protection_scope_id=(
                        protection_scope_id
                    ),
                    scope_key_id=(
                        unlocked.scope_key_id
                    ),
                ),
            )

            encrypted = self.crypto.encrypt(
                bytes(
                    dek
                ),
                plaintext,
                aad=_payload_aad(
                    protected_payload_id=(
                        payload_id
                    ),
                    protection_scope_id=(
                        protection_scope_id
                    ),
                    scope_key_id=(
                        unlocked.scope_key_id
                    ),
                ),
            )

            return ProtectedPayloadRecord(
                protected_payload_id=(
                    payload_id
                ),
                protection_scope_id=(
                    protection_scope_id
                ),
                scope_key_id=(
                    unlocked.scope_key_id
                ),
                cipher_suite=(
                    AES_256_GCM
                ),
                ciphertext=(
                    encrypted.ciphertext
                ),
                nonce=encrypted.nonce,
                wrapped_dek=(
                    wrapped_dek.ciphertext
                ),
                dek_wrap_nonce=(
                    wrapped_dek.nonce
                ),
                aad_version=_AAD_VERSION,
                ciphertext_hash=(
                    self.crypto
                    .ciphertext_hash(
                        encrypted.ciphertext
                    )
                ),
                created_at_us=(
                    created_at_us
                ),
            )

        finally:
            _wipe(
                dek
            )

    def load_payload(
        self,
        protected_payload_id: uuid.UUID,
    ) -> bytes:
        record = (
            self.repository.get_payload(
                protected_payload_id
            )
        )

        unlocked = self._require_unlocked(
            record.protection_scope_id,
            expected_scope_key_id=(
                record.scope_key_id
            ),
        )

        if (
            record.cipher_suite
            != AES_256_GCM
        ):
            raise (
                ProtectedContentIntegrityError(
                    "Protected payload cipher "
                    "suite is unsupported."
                )
            )

        if (
            record.aad_version
            != _AAD_VERSION
        ):
            raise (
                ProtectedContentIntegrityError(
                    "Protected payload AAD "
                    "version is unsupported."
                )
            )

        expected_hash = (
            self.crypto.ciphertext_hash(
                record.ciphertext
            )
        )

        if not hmac.compare_digest(
            expected_hash,
            record.ciphertext_hash,
        ):
            raise (
                ProtectedContentIntegrityError(
                    "Protected payload "
                    "authentication failed."
                )
            )

        try:
            dek = bytearray(
                self.crypto.decrypt(
                    bytes(
                        unlocked.key
                    ),
                    nonce=(
                        record.dek_wrap_nonce
                    ),
                    ciphertext=(
                        record.wrapped_dek
                    ),
                    aad=_payload_dek_aad(
                        protected_payload_id=(
                            record
                            .protected_payload_id
                        ),
                        protection_scope_id=(
                            record
                            .protection_scope_id
                        ),
                        scope_key_id=(
                            record.scope_key_id
                        ),
                    ),
                )
            )

        except (
            CryptoAuthenticationError
        ) as exc:
            raise (
                ProtectedContentIntegrityError(
                    "Protected payload "
                    "authentication failed."
                )
            ) from exc

        try:
            try:
                return self.crypto.decrypt(
                    bytes(
                        dek
                    ),
                    nonce=record.nonce,
                    ciphertext=(
                        record.ciphertext
                    ),
                    aad=_payload_aad(
                        protected_payload_id=(
                            record
                            .protected_payload_id
                        ),
                        protection_scope_id=(
                            record
                            .protection_scope_id
                        ),
                        scope_key_id=(
                            record.scope_key_id
                        ),
                    ),
                )

            except (
                CryptoAuthenticationError
            ) as exc:
                raise (
                    ProtectedContentIntegrityError(
                        "Protected payload "
                        "authentication failed."
                    )
                ) from exc

        finally:
            _wipe(
                dek
            )

    def wrap_blob_dek(
        self,
        protection_scope_id: uuid.UUID,
        *,
        blob_id: uuid.UUID,
        dek: bytes,
        nonce_prefix: bytes,
        chunk_size: int,
        format_version: int,
    ) -> ProtectedBlobEnvelopeRecord:
        if len(dek) != KEY_BYTES:
            raise ValueError(
                "Protected Blob DEKs must contain exactly 32 bytes."
            )
        if len(nonce_prefix) != 8:
            raise ValueError(
                "Protected Blob nonce prefixes must contain exactly 8 bytes."
            )
        if chunk_size < 1:
            raise ValueError(
                "Protected Blob chunk size must be positive."
            )
        if format_version != 1:
            raise ValueError(
                "Unsupported Protected Blob format version."
            )

        unlocked = self._require_unlocked(
            protection_scope_id
        )
        current_key = self.repository.get_current_scope_key(
            protection_scope_id
        )
        if (
            current_key.scope_key_id != unlocked.scope_key_id
            or current_key.status is not KeyStatus.ACTIVE
        ):
            raise ProtectionScopeLockedError(
                "ProtectionScope key changed; unlock the scope again."
            )

        wrapped = self.crypto.encrypt(
            bytes(unlocked.key),
            dek,
            aad=_blob_dek_aad(
                blob_id=blob_id,
                protection_scope_id=protection_scope_id,
                scope_key_id=unlocked.scope_key_id,
                nonce_prefix=nonce_prefix,
                chunk_size=chunk_size,
                format_version=format_version,
            ),
        )
        return ProtectedBlobEnvelopeRecord(
            blob_id=blob_id,
            protection_scope_id=protection_scope_id,
            scope_key_id=unlocked.scope_key_id,
            wrapped_dek=wrapped.ciphertext,
            dek_wrap_nonce=wrapped.nonce,
            nonce_prefix=nonce_prefix,
            chunk_size=chunk_size,
            cipher_suite=AES_256_GCM,
            format_version=format_version,
        )

    def unwrap_blob_dek(
        self,
        envelope: ProtectedBlobEnvelopeRecord,
    ) -> bytearray:
        if (
            envelope.cipher_suite != AES_256_GCM
            or envelope.format_version != 1
            or len(envelope.nonce_prefix) != 8
            or envelope.chunk_size < 1
        ):
            raise ProtectedContentIntegrityError(
                "Protected Blob envelope metadata is invalid."
            )

        unlocked = self._require_unlocked(
            envelope.protection_scope_id,
            expected_scope_key_id=envelope.scope_key_id,
        )
        try:
            raw = self.crypto.decrypt(
                bytes(unlocked.key),
                nonce=envelope.dek_wrap_nonce,
                ciphertext=envelope.wrapped_dek,
                aad=_blob_dek_aad(
                    blob_id=envelope.blob_id,
                    protection_scope_id=envelope.protection_scope_id,
                    scope_key_id=envelope.scope_key_id,
                    nonce_prefix=envelope.nonce_prefix,
                    chunk_size=envelope.chunk_size,
                    format_version=envelope.format_version,
                ),
            )
        except CryptoAuthenticationError as exc:
            raise ProtectedContentIntegrityError(
                "Protected Blob DEK authentication failed."
            ) from exc

        if len(raw) != KEY_BYTES:
            raise ProtectedContentIntegrityError(
                "Protected Blob DEK has an invalid length."
            )
        return bytearray(raw)

    def _unwrap_root_key(
        self,
        password: bytes,
    ) -> bytearray:
        slot = (
            self.repository
            .active_password_slot()
        )

        if slot is None:
            raise (
                ProtectedContentNotInitializedError(
                    "ATHENA Protected Content "
                    "is not initialized."
                )
            )

        if (
            slot.slot_type
            is not KeySlotType.PASSWORD
            or
            slot.status
            is not KeyStatus.ACTIVE
            or
            slot.kdf_algorithm
            != ARGON2ID
            or
            slot.wrap_algorithm
            != AES_256_GCM
        ):
            raise (
                ProtectedContentIntegrityError(
                    "Active password key slot "
                    "metadata is unsupported."
                )
            )

        kek = bytearray(
            self.crypto.derive_password_key(
                password,
                salt=slot.salt,
                parameters=(
                    slot.kdf_parameters
                ),
            )
        )

        try:
            try:
                root_key = bytearray(
                    self.crypto.decrypt(
                        bytes(
                            kek
                        ),
                        nonce=(
                            slot.wrap_nonce
                        ),
                        ciphertext=(
                            slot.wrapped_root_key
                        ),
                        aad=_key_slot_aad(
                            key_slot_id=(
                                slot.key_slot_id
                            ),
                            parameters=(
                                slot.kdf_parameters
                            ),
                            salt=slot.salt,
                        ),
                    )
                )

            except (
                CryptoAuthenticationError
            ) as exc:
                raise (
                    ProtectedContentUnlockError(
                        "Protected content "
                        "unlock failed."
                    )
                ) from exc

            if len(root_key) != KEY_BYTES:
                _wipe(
                    root_key
                )
                raise (
                    ProtectedContentIntegrityError(
                        "ATHENA Root Key has "
                        "an invalid length."
                    )
                )

            return root_key

        finally:
            _wipe(
                kek
            )

    def _require_unlocked(
        self,
        protection_scope_id: uuid.UUID,
        *,
        expected_scope_key_id: (
            uuid.UUID | None
        ) = None,
    ) -> _UnlockedScopeKey:
        unlocked = (
            self._unlocked_scope_keys.get(
                protection_scope_id
            )
        )

        if unlocked is None:
            raise ProtectionScopeLockedError(
                "ProtectionScope is locked."
            )

        if (
            expected_scope_key_id
            is not None
            and
            unlocked.scope_key_id
            != expected_scope_key_id
        ):
            raise ProtectionScopeLockedError(
                "Required ProtectionScope key "
                "is not unlocked."
            )

        return unlocked


def _normalize_neutral_label(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    if not normalized:
        return None

    if len(normalized) > 128:
        raise ValueError(
            "neutral_label must not exceed "
            "128 characters."
        )

    return normalized


def _canonical_aad(
    kind: str,
    fields: dict[str, str | int],
) -> bytes:
    document: dict[str, object] = {
        "format": "athena-protected-aad",
        "format_version": 1,
        "kind": kind,
        "fields": fields,
    }

    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode(
        "utf-8"
    )


def _key_slot_aad(
    *,
    key_slot_id: uuid.UUID,
    parameters: Argon2idParameters,
    salt: bytes,
) -> bytes:
    return _canonical_aad(
        "root-key-wrap",
        {
            "key_slot_id": str(
                key_slot_id
            ),
            "slot_type": (
                KeySlotType.PASSWORD.value
            ),
            "kdf_algorithm": ARGON2ID,
            "kdf_parameters": (
                parameters.to_json()
            ),
            "salt_hex": salt.hex(),
            "wrap_algorithm": (
                AES_256_GCM
            ),
        },
    )


def _scope_key_aad(
    *,
    protection_scope_id: uuid.UUID,
    scope_key_id: uuid.UUID,
    key_version: int,
) -> bytes:
    return _canonical_aad(
        "scope-key-wrap",
        {
            "protection_scope_id": str(
                protection_scope_id
            ),
            "scope_key_id": str(
                scope_key_id
            ),
            "key_version": key_version,
            "wrap_algorithm": (
                AES_256_GCM
            ),
        },
    )


def _payload_dek_aad(
    *,
    protected_payload_id: uuid.UUID,
    protection_scope_id: uuid.UUID,
    scope_key_id: uuid.UUID,
) -> bytes:
    return _canonical_aad(
        "payload-dek-wrap",
        {
            "protected_payload_id": str(
                protected_payload_id
            ),
            "protection_scope_id": str(
                protection_scope_id
            ),
            "scope_key_id": str(
                scope_key_id
            ),
            "aad_version": (
                _AAD_VERSION
            ),
            "wrap_algorithm": (
                AES_256_GCM
            ),
        },
    )


def _payload_aad(
    *,
    protected_payload_id: uuid.UUID,
    protection_scope_id: uuid.UUID,
    scope_key_id: uuid.UUID,
) -> bytes:
    return _canonical_aad(
        "protected-payload",
        {
            "protected_payload_id": str(
                protected_payload_id
            ),
            "protection_scope_id": str(
                protection_scope_id
            ),
            "scope_key_id": str(
                scope_key_id
            ),
            "aad_version": (
                _AAD_VERSION
            ),
            "cipher_suite": (
                AES_256_GCM
            ),
        },
    )


def _blob_dek_aad(
    *,
    blob_id: uuid.UUID,
    protection_scope_id: uuid.UUID,
    scope_key_id: uuid.UUID,
    nonce_prefix: bytes,
    chunk_size: int,
    format_version: int,
) -> bytes:
    return json.dumps(
        {
            "blob_id": str(blob_id),
            "chunk_size": chunk_size,
            "domain": "athena.protected_blob.dek",
            "format_version": format_version,
            "nonce_prefix": nonce_prefix.hex(),
            "protection_scope_id": str(protection_scope_id),
            "scope_key_id": str(scope_key_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")

def _wipe(
    buffer: bytearray,
) -> None:
    for index in range(
        len(buffer)
    ):
        buffer[index] = 0
