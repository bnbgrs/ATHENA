"""Explicit-user lifecycle deletion with dependency preview."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.service import ChatService
from athena.common.ids import (
    new_uuid7,
    uuid_from_blob,
    uuid_to_blob,
)
from athena.common.time import utc_now_us
from athena.lifecycle.deletion import record_deletion
from athena.storage.database import (
    DatabaseSnapshotChangedError,
    SQLiteDatabase,
)


class LifecycleDeletionError(RuntimeError):
    """Base error for explicit lifecycle deletion."""


class LifecycleDeletionNotFoundError(LookupError):
    """Requested canonical entity does not exist."""


class LifecycleDeletionUnsupportedError(
    LifecycleDeletionError
):
    """Deletion scope has no safe implementation yet."""


class LifecycleDeletionAlreadyDeletedError(
    LifecycleDeletionError
):
    """Entity is already logically deleted."""


class LifecycleDeletionPreviewStaleError(
    LifecycleDeletionError
):
    """Dependencies changed since the user reviewed the delete."""


@dataclass(
    frozen=True,
    slots=True,
)
class DeletionDependency:
    """Payload-free dependency surfaced before deletion."""

    relation: str
    count: int
    dependent_entity_id: uuid.UUID | None = None
    dependent_entity_type: str | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class DeletionPreview:
    """Stable payload-free deletion impact preview."""

    entity_id: uuid.UUID
    entity_type: str
    lifecycle_state: str
    dependencies: tuple[
        DeletionDependency,
        ...,
    ]
    preview_digest: str


@dataclass(
    frozen=True,
    slots=True,
)
class DeletionResult:
    """Result of one explicit logical deletion commit."""

    entity_id: uuid.UUID
    entity_type: str
    commit_id: uuid.UUID
    deleted_entity_ids: tuple[
        uuid.UUID,
        ...,
    ]
    preview_digest: str


class LifecycleDeletionService:
    """Preview and execute user-authorized logical deletion."""

    _SUPPORTED_ENTITY_TYPES = frozenset(
        {
            "knowledge_unit",
            "source",
            "chat",
        }
    )

    _GENERIC_REFERENCE_COLUMNS = frozenset(
        {
            "attributed_to_entity_id",
            "chat_id",
            "input_entity_id",
            "knowledge_id",
            "object_entity_id",
            "scope_entity_id",
            "source_id",
            "subject_entity_id",
        }
    )

    _REFERENCE_SCAN_EXCLUDED_TABLES = frozenset(
        {
            "commit_changes",
            "deletion_ledger",
            "entity_heads",
            "entity_registry",
            "entity_state_history",
            "provenance_inputs",
            "provenance_records",
            "revisions",
        }
    )

    _OWNER_TABLES = {
        "knowledge_unit": frozenset(
            {
                "knowledge_units",
            }
        ),
        "source": frozenset(
            {
                "sources",
            }
        ),
        "chat": frozenset(
            {
                "chats",
            }
        ),
    }

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        deletion_sync: Callable[
            [],
            object,
        ]
        | None = None,
    ) -> None:
        self.database = database
        self.chat = chat
        self.deletion_sync = deletion_sync

    def preview(
        self,
        entity_id: uuid.UUID,
    ) -> DeletionPreview:
        preview, _snapshot = self.database.stable_read(
            lambda connection: self._preview_connection(
                connection,
                entity_id,
            )
        )
        return preview

    def delete(
        self,
        entity_id: uuid.UUID,
        *,
        preview_digest: str,
    ) -> DeletionResult:
        normalized_digest = (
            preview_digest.strip().lower()
        )

        if (
            len(normalized_digest) != 64
            or any(
                character
                not in "0123456789abcdef"
                for character in normalized_digest
            )
        ):
            raise ValueError(
                "preview_digest must be a SHA-256 hex digest."
            )

        actor_id = (
            self.chat.ensure_local_user()
        )

        preview, snapshot = self.database.stable_read(
            lambda connection: self._preview_connection(
                connection,
                entity_id,
            )
        )

        if (
            preview.preview_digest
            != normalized_digest
        ):
            raise LifecycleDeletionPreviewStaleError(
                "Deletion dependencies changed after preview; "
                "review the deletion again."
            )

        if (
            preview.lifecycle_state
            == "deleted"
        ):
            raise LifecycleDeletionAlreadyDeletedError(
                str(
                    entity_id
                )
            )

        deleted_at_us = (
            utc_now_us()
        )

        commit_id = (
            new_uuid7()
        )

        with self.database.write_transaction() as connection:
            try:
                self.database.assert_snapshot_current(
                    connection,
                    snapshot,
                )
            except DatabaseSnapshotChangedError as exc:
                raise LifecycleDeletionPreviewStaleError(
                    "Deletion dependencies changed after preview; "
                    "review the deletion again."
                ) from exc

            commit_seq = (
                self._insert_commit(
                    connection,
                    commit_id=commit_id,
                    actor_id=actor_id,
                    entity_type=preview.entity_type,
                    committed_at_us=deleted_at_us,
                )
            )

            deleted_entities: list[
                tuple[
                    uuid.UUID,
                    str,
                ]
            ] = [
                (
                    entity_id,
                    preview.entity_type,
                )
            ]

            if (
                preview.entity_type
                == "chat"
            ):
                child_rows = connection.execute(
                    """
                    SELECT
                        message.message_id,
                        registry.entity_type
                    FROM chat_messages AS message
                    JOIN entity_registry AS registry
                      ON registry.entity_id = message.message_id
                    WHERE message.chat_id = ?
                      AND registry.lifecycle_state != 'deleted'
                    ORDER BY message.sequence_no ASC,
                             message.message_id ASC
                    """,
                    (
                        uuid_to_blob(
                            entity_id
                        ),
                    ),
                ).fetchall()

                deleted_entities.extend(
                    (
                        uuid_from_blob(
                            bytes(
                                row[
                                    "message_id"
                                ]
                            )
                        ),
                        str(
                            row[
                                "entity_type"
                            ]
                        ),
                    )
                    for row in child_rows
                )

            for (
                deleted_entity_id,
                deleted_entity_type,
            ) in deleted_entities:
                self._mark_entity_deleted(
                    connection,
                    entity_id=deleted_entity_id,
                    actor_id=actor_id,
                    commit_seq=commit_seq,
                )

                if (
                    deleted_entity_type
                    == "chat"
                ):
                    updated = connection.execute(
                        """
                        UPDATE chats
                        SET lifecycle_state = 'deleted'
                        WHERE chat_id = ?
                        """,
                        (
                            uuid_to_blob(
                                deleted_entity_id
                            ),
                        ),
                    )

                    if updated.rowcount != 1:
                        raise LifecycleDeletionError(
                            "Chat lifecycle row is missing or ambiguous."
                        )

                record_deletion(
                    connection,
                    entity_id=deleted_entity_id,
                    entity_type=deleted_entity_type,
                    deleted_at_us=deleted_at_us,
                    deletion_commit_seq=commit_seq,
                    deleted_by_actor_id=actor_id,
                )

                connection.execute(
                    """
                    INSERT INTO commit_changes (
                        commit_seq,
                        entity_id,
                        revision_id,
                        change_type
                    ) VALUES (?, ?, NULL, 'deleted')
                    """,
                    (
                        commit_seq,
                        uuid_to_blob(
                            deleted_entity_id
                        ),
                    ),
                )

        if self.deletion_sync is not None:
            self.deletion_sync()

        return DeletionResult(
            entity_id=entity_id,
            entity_type=preview.entity_type,
            commit_id=commit_id,
            deleted_entity_ids=tuple(
                item[0]
                for item in deleted_entities
            ),
            preview_digest=preview.preview_digest,
        )

    def _preview_connection(
        self,
        connection: sqlite3.Connection,
        entity_id: uuid.UUID,
    ) -> DeletionPreview:
        entity_blob = (
            uuid_to_blob(
                entity_id
            )
        )

        row = connection.execute(
            """
            SELECT
                entity_type,
                lifecycle_state,
                protection_scope_id
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                entity_blob,
            ),
        ).fetchone()

        if row is None:
            raise LifecycleDeletionNotFoundError(
                str(
                    entity_id
                )
            )

        entity_type = str(
            row[
                "entity_type"
            ]
        )

        lifecycle_state = str(
            row[
                "lifecycle_state"
            ]
        )

        if (
            entity_type
            not in self._SUPPORTED_ENTITY_TYPES
        ):
            if entity_type == "project":
                raise LifecycleDeletionUnsupportedError(
                    "Project deletion is unavailable because "
                    "ATHENA does not yet have a canonical Project "
                    "lifecycle implementation."
                )

            raise LifecycleDeletionUnsupportedError(
                "No explicit safe deletion handler exists for "
                f"entity type {entity_type!r}."
            )

        if (
            row[
                "protection_scope_id"
            ]
            is not None
        ):
            raise LifecycleDeletionUnsupportedError(
                "Protected entity deletion is reserved for "
                "the protected physical-purge slice."
            )

        dependencies: list[
            DeletionDependency
        ] = []

        self._append_provenance_dependents(
            connection,
            entity_id=entity_id,
            dependencies=dependencies,
        )

        if entity_type == "source":
            source_row = connection.execute(
                """
                SELECT source.blob_id
                FROM sources AS source
                WHERE source.source_id = ?
                """,
                (
                    entity_blob,
                ),
            ).fetchone()

            if source_row is None:
                raise LifecycleDeletionError(
                    "Source entity has no canonical source row."
                )

            blob_id = uuid_from_blob(
                bytes(
                    source_row[
                        "blob_id"
                    ]
                )
            )

            blob_type_row = connection.execute(
                """
                SELECT entity_type
                FROM entity_registry
                WHERE entity_id = ?
                """,
                (
                    uuid_to_blob(
                        blob_id
                    ),
                ),
            ).fetchone()

            dependencies.append(
                DeletionDependency(
                    relation="source.blob_reference",
                    count=1,
                    dependent_entity_id=blob_id,
                    dependent_entity_type=(
                        str(
                            blob_type_row[
                                "entity_type"
                            ]
                        )
                        if blob_type_row
                        is not None
                        else "blob_record"
                    ),
                )
            )

        if entity_type == "chat":
            child_rows = connection.execute(
                """
                SELECT
                    message.message_id,
                    registry.entity_type
                FROM chat_messages AS message
                JOIN entity_registry AS registry
                  ON registry.entity_id = message.message_id
                WHERE message.chat_id = ?
                  AND registry.lifecycle_state != 'deleted'
                ORDER BY message.sequence_no ASC,
                         message.message_id ASC
                """,
                (
                    entity_blob,
                ),
            ).fetchall()

            dependencies.extend(
                DeletionDependency(
                    relation="chat.owned_message",
                    count=1,
                    dependent_entity_id=uuid_from_blob(
                        bytes(
                            child[
                                "message_id"
                            ]
                        )
                    ),
                    dependent_entity_type=str(
                        child[
                            "entity_type"
                        ]
                    ),
                )
                for child in child_rows
            )

        self._append_schema_references(
            connection,
            entity_id=entity_id,
            entity_type=entity_type,
            dependencies=dependencies,
        )

        normalized = tuple(
            sorted(
                self._deduplicate_dependencies(
                    dependencies
                ),
                key=self._dependency_sort_key,
            )
        )

        preview_digest = (
            self._preview_digest(
                entity_id=entity_id,
                entity_type=entity_type,
                lifecycle_state=lifecycle_state,
                dependencies=normalized,
            )
        )

        return DeletionPreview(
            entity_id=entity_id,
            entity_type=entity_type,
            lifecycle_state=lifecycle_state,
            dependencies=normalized,
            preview_digest=preview_digest,
        )

    @staticmethod
    def _append_provenance_dependents(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        dependencies: list[
            DeletionDependency
        ],
    ) -> None:
        rows = connection.execute(
            """
            SELECT DISTINCT
                provenance.subject_entity_id,
                registry.entity_type
            FROM provenance_inputs AS input
            JOIN provenance_records AS provenance
              ON provenance.provenance_id = input.provenance_id
            JOIN entity_registry AS registry
              ON registry.entity_id = provenance.subject_entity_id
            WHERE input.input_entity_id = ?
              AND provenance.subject_entity_id != ?
              AND registry.lifecycle_state != 'deleted'
            ORDER BY provenance.subject_entity_id ASC
            """,
            (
                uuid_to_blob(
                    entity_id
                ),
                uuid_to_blob(
                    entity_id
                ),
            ),
        ).fetchall()

        dependencies.extend(
            DeletionDependency(
                relation="provenance.dependent_entity",
                count=1,
                dependent_entity_id=uuid_from_blob(
                    bytes(
                        row[
                            "subject_entity_id"
                        ]
                    )
                ),
                dependent_entity_type=str(
                    row[
                        "entity_type"
                    ]
                ),
            )
            for row in rows
        )

    def _append_schema_references(
        self,
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        entity_type: str,
        dependencies: list[
            DeletionDependency
        ],
    ) -> None:
        entity_blob = uuid_to_blob(
            entity_id
        )

        tables = tuple(
            str(
                row[
                    "name"
                ]
            )
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        )

        owner_tables = (
            self._OWNER_TABLES.get(
                entity_type,
                frozenset(),
            )
        )

        for table in tables:
            if (
                table
                in self._REFERENCE_SCAN_EXCLUDED_TABLES
                or table in owner_tables
            ):
                continue

            quoted_table = (
                self._quote_identifier(
                    table
                )
            )

            columns = tuple(
                str(
                    row[
                        "name"
                    ]
                )
                for row in connection.execute(
                    f"PRAGMA table_info({quoted_table})"
                ).fetchall()
            )

            for column in columns:
                if (
                    column
                    not in self._GENERIC_REFERENCE_COLUMNS
                ):
                    continue

                if (
                    table == "chat_messages"
                    and column == "chat_id"
                    and entity_type == "chat"
                ):
                    continue

                quoted_column = (
                    self._quote_identifier(
                        column
                    )
                )

                count = int(
                    connection.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {quoted_table}
                        WHERE {quoted_column} = ?
                        """,
                        (
                            entity_blob,
                        ),
                    ).fetchone()[0]
                )

                if count <= 0:
                    continue

                dependencies.append(
                    DeletionDependency(
                        relation=(
                            f"table.{table}.{column}"
                        ),
                        count=count,
                    )
                )

    @staticmethod
    def _quote_identifier(
        value: str,
    ) -> str:
        if "\x00" in value:
            raise LifecycleDeletionError(
                "Unsafe SQLite identifier."
            )

        return (
            '"'
            + value.replace(
                '"',
                '""',
            )
            + '"'
        )

    @staticmethod
    def _deduplicate_dependencies(
        dependencies: list[
            DeletionDependency
        ],
    ) -> tuple[
        DeletionDependency,
        ...,
    ]:
        unique: dict[
            tuple[
                str,
                int,
                uuid.UUID | None,
                str | None,
            ],
            DeletionDependency,
        ] = {}

        for dependency in dependencies:
            key = (
                dependency.relation,
                dependency.count,
                dependency.dependent_entity_id,
                dependency.dependent_entity_type,
            )

            unique[
                key
            ] = dependency

        return tuple(
            unique.values()
        )

    @staticmethod
    def _dependency_sort_key(
        dependency: DeletionDependency,
    ) -> tuple[
        str,
        str,
        str,
        int,
    ]:
        return (
            dependency.relation,
            (
                dependency.dependent_entity_type
                or ""
            ),
            (
                str(
                    dependency.dependent_entity_id
                )
                if dependency.dependent_entity_id
                is not None
                else ""
            ),
            dependency.count,
        )

    @classmethod
    def _preview_digest(
        cls,
        *,
        entity_id: uuid.UUID,
        entity_type: str,
        lifecycle_state: str,
        dependencies: tuple[
            DeletionDependency,
            ...,
        ],
    ) -> str:
        payload = {
            "dependencies": [
                {
                    "count": dependency.count,
                    "dependent_entity_id": (
                        str(
                            dependency.dependent_entity_id
                        )
                        if dependency.dependent_entity_id
                        is not None
                        else None
                    ),
                    "dependent_entity_type": (
                        dependency.dependent_entity_type
                    ),
                    "relation": (
                        dependency.relation
                    ),
                }
                for dependency in dependencies
            ],
            "entity_id": str(
                entity_id
            ),
            "entity_type": entity_type,
            "lifecycle_state": lifecycle_state,
        }

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            allow_nan=False,
        ).encode(
            "utf-8"
        )

        return hashlib.sha256(
            encoded
        ).hexdigest()

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
        entity_type: str,
        committed_at_us: int,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id,
                committed_at_us,
                actor_id,
                operation_type,
                reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(
                    commit_id
                ),
                committed_at_us,
                uuid_to_blob(
                    actor_id
                ),
                (
                    "lifecycle.delete."
                    + entity_type
                ),
                (
                    "explicit user lifecycle deletion"
                ),
            ),
        )

        if cursor.lastrowid is None:
            raise LifecycleDeletionError(
                "SQLite did not return a deletion commit sequence."
            )

        return int(
            cursor.lastrowid
        )

    @staticmethod
    def _mark_entity_deleted(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        actor_id: uuid.UUID,
        commit_seq: int,
    ) -> None:
        entity_blob = (
            uuid_to_blob(
                entity_id
            )
        )

        row = connection.execute(
            """
            SELECT
                lifecycle_state,
                protection_scope_id
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                entity_blob,
            ),
        ).fetchone()

        if row is None:
            raise LifecycleDeletionError(
                "Deletion target disappeared during transaction."
            )

        if (
            str(
                row[
                    "lifecycle_state"
                ]
            )
            == "deleted"
        ):
            return

        closed = connection.execute(
            """
            UPDATE entity_state_history
            SET valid_to_commit_seq = ?
            WHERE entity_id = ?
              AND valid_to_commit_seq IS NULL
            """,
            (
                commit_seq,
                entity_blob,
            ),
        )

        if closed.rowcount != 1:
            raise LifecycleDeletionError(
                "Entity has ambiguous open lifecycle history."
            )

        protection_scope = (
            bytes(
                row[
                    "protection_scope_id"
                ]
            )
            if row[
                "protection_scope_id"
            ]
            is not None
            else None
        )

        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (
                ?,
                ?,
                NULL,
                'deleted',
                ?,
                ?,
                'explicit user lifecycle deletion'
            )
            """,
            (
                entity_blob,
                commit_seq,
                protection_scope,
                uuid_to_blob(
                    actor_id
                ),
            ),
        )

        updated = connection.execute(
            """
            UPDATE entity_registry
            SET lifecycle_state = 'deleted'
            WHERE entity_id = ?
            """,
            (
                entity_blob,
            ),
        )

        if updated.rowcount != 1:
            raise LifecycleDeletionError(
                "Entity registry deletion update failed."
            )
