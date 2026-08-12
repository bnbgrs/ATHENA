"""Persistent reproducibility metadata for SourceChunk profiles."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.storage.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class ChunkingProfile:
    chunking_profile_id: uuid.UUID
    algorithm: str
    tokenizer: str | None
    target_size: int | None
    overlap_size: int | None
    structure_rules_json: str
    profile_version: int
    configuration_hash: bytes
    created_at_us: int


_DEFAULT_STRUCTURE_RULES = {
    "anchor_unit": "unicode_codepoint_offset",
    "boundary_priority": ["paragraph", "line", "whitespace", "hard_limit"],
    "preserve_exact_text_slices": True,
}
_DOCUMENT_STRUCTURE_RULES = {
    "anchor_unit": "unicode_codepoint_offset",
    "boundary_priority": [
        "document_block",
        "nested_structure",
        "line",
        "whitespace",
        "hard_limit",
    ],
    "preserve_exact_text_slices": True,
    "structure_map": "retained_v1",
}
_DEFAULT_ALGORITHM = "paragraph_char_v1"
_DOCUMENT_ALGORITHM = "document_structure_char_v1"
_DEFAULT_TARGET_SIZE = 1200
_DEFAULT_OVERLAP_SIZE = 0
_DEFAULT_PROFILE_VERSION = 1


class ChunkingProfileRepository:
    """Store immutable versioned chunking configurations in canonical metadata."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_or_create_default(self) -> ChunkingProfile:
        return self.get_or_create(
            algorithm=_DEFAULT_ALGORITHM,
            tokenizer=None,
            target_size=_DEFAULT_TARGET_SIZE,
            overlap_size=_DEFAULT_OVERLAP_SIZE,
            structure_rules=dict(_DEFAULT_STRUCTURE_RULES),
            profile_version=_DEFAULT_PROFILE_VERSION,
        )

    def get_or_create_document_default(self) -> ChunkingProfile:
        return self.get_or_create(
            algorithm=_DOCUMENT_ALGORITHM,
            tokenizer=None,
            target_size=_DEFAULT_TARGET_SIZE,
            overlap_size=_DEFAULT_OVERLAP_SIZE,
            structure_rules=dict(_DOCUMENT_STRUCTURE_RULES),
            profile_version=_DEFAULT_PROFILE_VERSION,
        )

    def get_or_create(
        self,
        *,
        algorithm: str,
        tokenizer: str | None,
        target_size: int | None,
        overlap_size: int | None,
        structure_rules: dict[str, object],
        profile_version: int,
    ) -> ChunkingProfile:
        normalized_algorithm = algorithm.strip()
        if not normalized_algorithm:
            raise ValueError("Chunking algorithm must not be empty.")
        if target_size is not None and target_size <= 0:
            raise ValueError("Chunking target_size must be positive when set.")
        if overlap_size is not None and overlap_size < 0:
            raise ValueError("Chunking overlap_size must not be negative.")
        if profile_version <= 0:
            raise ValueError("Chunking profile_version must be positive.")

        structure_rules_json = _canonical_json(structure_rules)
        configuration = {
            "algorithm": normalized_algorithm,
            "tokenizer": tokenizer,
            "target_size": target_size,
            "overlap_size": overlap_size,
            "structure_rules": json.loads(structure_rules_json),
            "profile_version": profile_version,
        }
        configuration_hash = hashlib.sha256(
            _canonical_json(configuration).encode("utf-8")
        ).digest()

        with self.database.write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM chunking_profiles WHERE configuration_hash = ?",
                (configuration_hash,),
            ).fetchone()
            if row is not None:
                return _profile_from_row(row)

            profile_id = new_uuid7()
            created_at_us = utc_now_us()
            connection.execute(
                """
                INSERT INTO chunking_profiles (
                    chunking_profile_id, algorithm, tokenizer, target_size,
                    overlap_size, structure_rules_json, profile_version,
                    configuration_hash, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(profile_id),
                    normalized_algorithm,
                    tokenizer,
                    target_size,
                    overlap_size,
                    structure_rules_json,
                    profile_version,
                    configuration_hash,
                    created_at_us,
                ),
            )

        return ChunkingProfile(
            chunking_profile_id=profile_id,
            algorithm=normalized_algorithm,
            tokenizer=tokenizer,
            target_size=target_size,
            overlap_size=overlap_size,
            structure_rules_json=structure_rules_json,
            profile_version=profile_version,
            configuration_hash=configuration_hash,
            created_at_us=created_at_us,
        )

    def get(self, chunking_profile_id: uuid.UUID) -> ChunkingProfile:
        row = self.database.connection.execute(
            "SELECT * FROM chunking_profiles WHERE chunking_profile_id = ?",
            (uuid_to_blob(chunking_profile_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"ChunkingProfile {chunking_profile_id} not found.")
        return _profile_from_row(row)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _profile_from_row(row: sqlite3.Row) -> ChunkingProfile:
    return ChunkingProfile(
        chunking_profile_id=uuid_from_blob(row["chunking_profile_id"]),
        algorithm=str(row["algorithm"]),
        tokenizer=(str(row["tokenizer"]) if row["tokenizer"] is not None else None),
        target_size=(int(row["target_size"]) if row["target_size"] is not None else None),
        overlap_size=(int(row["overlap_size"]) if row["overlap_size"] is not None else None),
        structure_rules_json=str(row["structure_rules_json"]),
        profile_version=int(row["profile_version"]),
        configuration_hash=bytes(row["configuration_hash"]),
        created_at_us=int(row["created_at_us"]),
    )
