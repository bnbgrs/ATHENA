from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from athena.common.ids import uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.source.anchor_service import SourceAnchorIntegrityError
from athena.source.protected_semantic import (
    ANCHOR_SEMANTIC_KIND,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticNotFoundError,
    SourceProtectedSemanticRepository,
    anchor_neutral_quoted_hash,
    decode_source_anchor_semantics,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


@pytest.fixture
def app(tmp_path: Path) -> Iterator[AthenaApplication]:
    instance = AthenaApplication(
        AthenaSettings(
            local_root=tmp_path / "runtime"
        )
    )
    instance.start()

    try:
        yield instance
    finally:
        instance.stop()


def _scope(
    app: AthenaApplication,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    scope = app.protected_content.create_scope(
        password,
        neutral_label="anchor-semantic-test",
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _source(
    app: AthenaApplication,
    tmp_path: Path,
    name: str,
    text: str,
):
    path = tmp_path / name
    path.write_text(
        text,
        encoding="utf-8",
        newline="",
    )

    source = app.sources.capture_file(path).source

    representation = (
        app.source_text
        .build(source.source_id)
        .result
        .representation
    )

    return source, representation


def _anchor(
    app: AthenaApplication,
    representation_id: uuid.UUID,
    text: str,
    needle: str,
):
    start = text.index(needle)

    return app.source_anchors.materialize_text_range(
        representation_id,
        start_offset=start,
        end_offset=start + len(needle),
    )


def _writer(
    app: AthenaApplication,
    scope_id: uuid.UUID,
    calls: list[bytes] | None = None,
):
    def write(
        connection: sqlite3.Connection,
        plaintext: bytes,
    ) -> uuid.UUID:
        if calls is not None:
            calls.append(plaintext)

        record = app.protected_content.prepare_payload(
            scope_id,
            plaintext,
        )

        app.protection_repository.insert_payload_in_transaction(
            connection,
            record,
        )

        return record.protected_payload_id

    return write


def _row(
    app: AthenaApplication,
    anchor_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT
            anchor_id,
            source_id,
            anchor_type,
            representation_id,
            start_offset,
            end_offset,
            geometry_json,
            quoted_hash
        FROM source_anchors
        WHERE anchor_id = ?
        """,
        (uuid_to_blob(anchor_id),),
    ).fetchone()


def test_anchor_semantics_protect_roundtrip_and_reader_fail_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = (
        "prefix "
        "ATHENA_ANCHOR_TEXT_CANARY "
        "suffix"
    )

    source, representation = _source(
        app,
        tmp_path,
        "anchor.txt",
        text,
    )

    anchor = _anchor(
        app,
        representation.representation_id,
        text,
        "ATHENA_ANCHOR_TEXT_CANARY",
    )

    assert anchor.quoted_hash is not None

    original_hash = anchor.quoted_hash

    original_geometry = json.dumps(
        {
            "label": "ATHENA_ANCHOR_GEOMETRY_CANARY",
            "x": 0.125,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_anchors
            SET geometry_json = ?
            WHERE anchor_id = ?
            """,
            (
                original_geometry,
                uuid_to_blob(anchor.anchor_id),
            ),
        )

    scope = _scope(
        app,
        b"anchor-semantic-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    with app.database.write_transaction() as connection:
        mappings = (
            repository
            .protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )
        )

    assert len(mappings) == 1

    mapping = mappings[0]

    assert mapping.semantic_kind == (
        ANCHOR_SEMANTIC_KIND
    )

    assert mapping.entity_id == anchor.anchor_id

    row = _row(
        app,
        anchor.anchor_id,
    )

    assert row is not None
    assert str(row["geometry_json"]) == "{}"

    assert bytes(row["quoted_hash"]) == (
        anchor_neutral_quoted_hash(
            anchor.anchor_id
        )
    )

    assert bytes(row["quoted_hash"]) != (
        original_hash
    )

    decoded = decode_source_anchor_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )

    assert decoded.anchor_id == anchor.anchor_id

    assert decoded.geometry_json == (
        original_geometry
    )

    assert decoded.quoted_hash == original_hash

    with pytest.raises(
        SourceAnchorIntegrityError,
        match="quoted hash disagrees",
    ):
        app.source_anchors.verify(
            anchor.anchor_id
        )


def test_original_nulls_survive_only_in_protected_payload(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = "whole source fixture"

    source, representation = _source(
        app,
        tmp_path,
        "whole.txt",
        text,
    )

    anchor = _anchor(
        app,
        representation.representation_id,
        text,
        "whole",
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_anchors
            SET anchor_type = 'whole_source',
                representation_id = NULL,
                start_offset = NULL,
                end_offset = NULL,
                page_start = NULL,
                page_end = NULL,
                geometry_json = NULL,
                quoted_hash = NULL
            WHERE anchor_id = ?
            """,
            (
                uuid_to_blob(anchor.anchor_id),
            ),
        )

    scope = _scope(
        app,
        b"anchor-null-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    with app.database.write_transaction() as connection:
        mapping = repository.protect_anchor_semantics(
            connection,
            source_id=source.source_id,
            anchor_id=anchor.anchor_id,
            protection_scope_id=(
                scope.protection_scope_id
            ),
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    row = _row(
        app,
        anchor.anchor_id,
    )

    assert row is not None
    assert str(row["geometry_json"]) == "{}"

    assert bytes(row["quoted_hash"]) == (
        anchor_neutral_quoted_hash(
            anchor.anchor_id
        )
    )

    decoded = decode_source_anchor_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )

    assert decoded.geometry_json is None
    assert decoded.quoted_hash is None


def test_anchor_cutover_idempotent_and_mixed_state_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = "idempotent mixed anchor semantic"

    source, representation = _source(
        app,
        tmp_path,
        "idempotent.txt",
        text,
    )

    anchor = _anchor(
        app,
        representation.representation_id,
        text,
        "anchor",
    )

    scope = _scope(
        app,
        b"anchor-idempotent-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    calls: list[bytes] = []

    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        first = (
            repository
            .protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )
        )

    payload_count = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )

    with app.database.write_transaction() as connection:
        second = (
            repository
            .protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )
        )

    assert second == first
    assert len(calls) == 1

    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    ) == payload_count

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_anchors
            SET geometry_json = ?
            WHERE anchor_id = ?
            """,
            (
                (
                    '{"leak":'
                    '"ATHENA_MIXED_STATE_CANARY"}'
                ),
                uuid_to_blob(anchor.anchor_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="not fully neutralized",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

    assert len(calls) == 1


def test_second_anchor_failure_rolls_back_first_anchor_and_payload(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = (
        "first anchor region "
        "then second anchor region"
    )

    source, representation = _source(
        app,
        tmp_path,
        "rollback.txt",
        text,
    )

    first = _anchor(
        app,
        representation.representation_id,
        text,
        "first anchor",
    )

    second = _anchor(
        app,
        representation.representation_id,
        text,
        "second anchor",
    )

    scope = _scope(
        app,
        b"anchor-rollback-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    ordered = sorted(
        (
            first.anchor_id,
            second.anchor_id,
        ),
        key=lambda item: item.bytes,
    )

    failing_id = ordered[1]

    before_rows = tuple(
        tuple(row)
        for row
        in app.database.connection.execute(
            """
            SELECT
                anchor_id,
                geometry_json,
                quoted_hash
            FROM source_anchors
            WHERE source_id = ?
            ORDER BY anchor_id
            """,
            (
                uuid_to_blob(source.source_id),
            ),
        ).fetchall()
    )

    before_payloads = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            f"""
            CREATE TRIGGER fail_second_anchor_mapping
            BEFORE INSERT
            ON source_protected_semantic_payloads
            WHEN NEW.semantic_kind = '{ANCHOR_SEMANTIC_KIND}'
             AND hex(NEW.entity_id) = '{failing_id.hex.upper()}'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'forced anchor mapping failure'
                );
            END
            """
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="mapping violates",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )

    after_rows = tuple(
        tuple(row)
        for row
        in app.database.connection.execute(
            """
            SELECT
                anchor_id,
                geometry_json,
                quoted_hash
            FROM source_anchors
            WHERE source_id = ?
            ORDER BY anchor_id
            """,
            (
                uuid_to_blob(source.source_id),
            ),
        ).fetchall()
    )

    assert after_rows == before_rows

    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    ) == before_payloads

    assert int(
        app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_protected_semantic_payloads
            WHERE source_id = ?
              AND semantic_kind = ?
            """,
            (
                uuid_to_blob(source.source_id),
                ANCHOR_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_text_range_unique_index_survives_neutral_hashes(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = "same range anchor uniqueness"

    source, representation = _source(
        app,
        tmp_path,
        "unique.txt",
        text,
    )

    first = _anchor(
        app,
        representation.representation_id,
        text,
        "same range",
    )

    first_row = _row(
        app,
        first.anchor_id,
    )

    assert first_row is not None

    second_id = uuid.uuid4()

    registry = app.database.connection.execute(
        """
        SELECT created_by_actor_id
        FROM entity_registry
        WHERE entity_id = ?
        """,
        (
            uuid_to_blob(first.anchor_id),
        ),
    ).fetchone()

    assert registry is not None

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            INSERT INTO entity_registry (
                entity_id,
                entity_type,
                domain,
                created_at_us,
                created_by_actor_id,
                lifecycle_state,
                protection_scope_id,
                schema_version
            ) VALUES (
                ?,
                'source_anchor',
                'raw_archive',
                ?,
                ?,
                'active',
                NULL,
                1
            )
            """,
            (
                uuid_to_blob(second_id),
                utc_now_us(),
                bytes(
                    registry[
                        "created_by_actor_id"
                    ]
                ),
            ),
        )

        connection.execute(
            """
            INSERT INTO source_anchors (
                anchor_id,
                source_id,
                representation_id,
                anchor_type,
                start_offset,
                end_offset,
                page_start,
                page_end,
                start_time_ms,
                end_time_ms,
                geometry_json,
                quoted_hash
            ) VALUES (
                ?,
                ?,
                ?,
                'text_range',
                ?,
                ?,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                ?
            )
            """,
            (
                uuid_to_blob(second_id),
                uuid_to_blob(source.source_id),
                uuid_to_blob(
                    representation.representation_id
                ),
                int(first_row["start_offset"]),
                int(first_row["end_offset"]),
                hashlib.sha256(
                    b"distinct-original-evidence-hash"
                ).digest(),
            ),
        )

    scope = _scope(
        app,
        b"anchor-unique-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    with app.database.write_transaction() as connection:
        mappings = (
            repository
            .protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )
        )

    assert len(mappings) == 2

    rows = app.database.connection.execute(
        """
        SELECT anchor_id, quoted_hash
        FROM source_anchors
        WHERE source_id = ?
        """,
        (
            uuid_to_blob(source.source_id),
        ),
    ).fetchall()

    hashes = {
        bytes(row["quoted_hash"])
        for row in rows
    }

    assert len(hashes) == 2

    for row in rows:
        anchor_id = uuid.UUID(
            bytes=bytes(row["anchor_id"])
        )

        assert bytes(row["quoted_hash"]) == (
            anchor_neutral_quoted_hash(
                anchor_id
            )
        )

    assert tuple(
        app.database.connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()
    ) == ("ok",)


def test_missing_wrong_and_empty_source_paths_encrypt_nothing(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = "source ownership anchor"

    source, representation = _source(
        app,
        tmp_path,
        "owned.txt",
        text,
    )

    anchor = _anchor(
        app,
        representation.representation_id,
        text,
        "anchor",
    )

    other_source, _ = _source(
        app,
        tmp_path,
        "other.txt",
        "other source",
    )

    scope = _scope(
        app,
        b"anchor-source-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    calls: list[bytes] = []

    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="does not belong",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_anchor_semantics(
                connection,
                source_id=other_source.source_id,
                anchor_id=anchor.anchor_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

    with pytest.raises(
        SourceProtectedSemanticNotFoundError
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_anchor_semantics(
                connection,
                source_id=uuid.uuid4(),
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

    with app.database.write_transaction() as connection:
        result = (
            repository
            .protect_source_anchor_semantics(
                connection,
                source_id=other_source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )
        )

    assert result == ()
    assert calls == []


def test_requires_transaction_and_rejects_neutral_hash_without_mapping(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    text = "pre neutral anchor"

    source, representation = _source(
        app,
        tmp_path,
        "preneutral.txt",
        text,
    )

    anchor = _anchor(
        app,
        representation.representation_id,
        text,
        "anchor",
    )

    scope = _scope(
        app,
        b"anchor-preneutral-password",
    )

    repository = SourceProtectedSemanticRepository(
        app.database
    )

    calls: list[bytes] = []

    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with pytest.raises(
        RuntimeError,
        match="active transaction",
    ):
        repository.protect_source_anchor_semantics(
            app.database.connection,
            source_id=source.source_id,
            protection_scope_id=(
                scope.protection_scope_id
            ),
            payload_writer=writer,
        )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_anchors
            SET geometry_json = '{}',
                quoted_hash = ?
            WHERE anchor_id = ?
            """,
            (
                anchor_neutral_quoted_hash(
                    anchor.anchor_id
                ),
                uuid_to_blob(anchor.anchor_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="without a protected mapping",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_anchor_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

    assert calls == []
