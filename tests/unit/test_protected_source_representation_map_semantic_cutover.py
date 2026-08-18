from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.source.protected_semantic import (
    PAGE_MAP_SEMANTIC_KIND,
    STRUCTURE_MAP_SEMANTIC_KIND,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticRepository,
    decode_representation_page_map_semantics,
    decode_representation_structure_map_semantics,
    page_neutral_content_hash,
    structure_neutral_content_hash,
    structure_neutral_path,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(local_root=root)
    )
    app.start()
    return app


def _scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    scope = app.protected_content.create_scope(
        password,
        neutral_label="representation-map-semantic-test",
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _representation(
    app: AthenaApplication,
    tmp_path: Path,
):
    path = tmp_path / "map-semantic-source.txt"

    path.write_text(
        (
            "ATHENA_PAGE_ONE_CANARY content alpha\n"
            "ATHENA_PAGE_TWO_CANARY content beta\n"
            "ATHENA_STRUCTURE_TEXT_CANARY gamma\n"
        ),
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


def _install_maps(
    app: AthenaApplication,
    representation_id: uuid.UUID,
):
    page_1_hash = hashlib.sha256(
        b"ATHENA_PAGE_HASH_CANARY_ONE"
    ).digest()
    page_2_hash = hashlib.sha256(
        b"ATHENA_PAGE_HASH_CANARY_TWO"
    ).digest()

    structure_1 = uuid.uuid4()
    structure_2 = uuid.uuid4()

    structure_1_hash = hashlib.sha256(
        b"ATHENA_STRUCTURE_HASH_CANARY_ONE"
    ).digest()
    structure_2_hash = hashlib.sha256(
        b"ATHENA_STRUCTURE_HASH_CANARY_TWO"
    ).digest()

    structure_1_path = (
        "/body/ATHENA_PRIVATE_HEADING_CANARY"
    )
    structure_2_path = (
        "/body/ATHENA_PRIVATE_HEADING_CANARY/"
        "child[1]"
    )

    metadata_1 = json.dumps(
        {
            "header": "ATHENA_SECRET_HEADER_CANARY",
            "style_name": "Sensitive Heading",
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    metadata_2 = json.dumps(
        {
            "document_title": (
                "ATHENA_SECRET_DOCUMENT_TITLE_CANARY"
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    pages = (
        (
            1,
            0,
            32,
            page_1_hash,
        ),
        (
            2,
            33,
            64,
            page_2_hash,
        ),
    )

    structures = (
        (
            structure_1,
            0,
            "heading",
            structure_1_path,
            None,
            0,
            32,
            structure_1_hash,
            metadata_1,
        ),
        (
            structure_2,
            1,
            "paragraph",
            structure_2_path,
            structure_1,
            33,
            64,
            structure_2_hash,
            metadata_2,
        ),
    )

    with app.database.write_transaction() as connection:
        connection.executemany(
            """
            INSERT INTO source_representation_pages (
                representation_id,
                page_number,
                start_offset,
                end_offset,
                content_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            tuple(
                (
                    representation_id.bytes,
                    page_number,
                    start_offset,
                    end_offset,
                    content_hash,
                )
                for (
                    page_number,
                    start_offset,
                    end_offset,
                    content_hash,
                ) in pages
            ),
        )

        for (
            structure_id,
            structure_index,
            structure_type,
            path,
            parent_id,
            start_offset,
            end_offset,
            content_hash,
            metadata_json,
        ) in structures:
            connection.execute(
                """
                INSERT INTO source_representation_structures (
                    structure_id,
                    representation_id,
                    structure_index,
                    structure_type,
                    path,
                    parent_structure_id,
                    start_offset,
                    end_offset,
                    content_hash,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    structure_id.bytes,
                    representation_id.bytes,
                    structure_index,
                    structure_type,
                    path,
                    (
                        None
                        if parent_id is None
                        else parent_id.bytes
                    ),
                    start_offset,
                    end_offset,
                    content_hash,
                    metadata_json,
                ),
            )

    return pages, structures


def _writer(
    app: AthenaApplication,
    protection_scope_id: uuid.UUID,
    *,
    calls: list[bytes] | None = None,
):
    def write(
        connection: sqlite3.Connection,
        plaintext: bytes,
    ) -> uuid.UUID:
        if calls is not None:
            calls.append(plaintext)

        record = app.protected_content.prepare_payload(
            protection_scope_id,
            plaintext,
        )

        app.protection_repository.insert_payload_in_transaction(
            connection,
            record,
        )

        return record.protected_payload_id

    return write


def _public_pages(
    app: AthenaApplication,
    representation_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT
            page_number,
            start_offset,
            end_offset,
            content_hash
        FROM source_representation_pages
        WHERE representation_id = ?
        ORDER BY page_number
        """,
        (representation_id.bytes,),
    ).fetchall()


def _public_structures(
    app: AthenaApplication,
    representation_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT
            structure_id,
            structure_index,
            structure_type,
            path,
            parent_structure_id,
            start_offset,
            end_offset,
            content_hash,
            metadata_json
        FROM source_representation_structures
        WHERE representation_id = ?
        ORDER BY structure_index
        """,
        (representation_id.bytes,),
    ).fetchall()


def test_page_and_structure_maps_are_protected_and_neutralized_atomically(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        original_pages, original_structures = _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"map-semantic-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        with app.database.write_transaction() as connection:
            mappings = (
                repository
                .protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                    ),
                )
            )

        assert {
            mapping.semantic_kind
            for mapping in mappings
        } == {
            PAGE_MAP_SEMANTIC_KIND,
            STRUCTURE_MAP_SEMANTIC_KIND,
        }

        pages = _public_pages(
            app,
            representation.representation_id,
        )

        assert len(pages) == 2

        for row in pages:
            page_number = int(row["page_number"])

            assert bytes(row["content_hash"]) == (
                page_neutral_content_hash(
                    representation.representation_id,
                    page_number,
                )
            )

        structures = _public_structures(
            app,
            representation.representation_id,
        )

        assert len(structures) == 2

        for row in structures:
            structure_id = uuid.UUID(
                bytes=bytes(row["structure_id"])
            )
            structure_index = int(
                row["structure_index"]
            )

            assert str(row["path"]) == structure_neutral_path(
                structure_id,
                structure_index,
            )

            assert bytes(row["content_hash"]) == (
                structure_neutral_content_hash(
                    structure_id
                )
            )

            assert str(row["metadata_json"]) == "{}"

        # Neutral relationship/provenance geometry remains intact.
        assert int(structures[0]["start_offset"]) == 0
        assert int(structures[1]["start_offset"]) == 33
        assert bytes(
            structures[1]["parent_structure_id"]
        ) == original_structures[0][0].bytes

        by_kind = {
            mapping.semantic_kind: mapping
            for mapping in mappings
        }

        page_payload = (
            app.protected_content.load_payload(
                by_kind[
                    PAGE_MAP_SEMANTIC_KIND
                ].protected_payload_id
            )
        )

        decoded_pages = (
            decode_representation_page_map_semantics(
                page_payload
            )
        )

        assert decoded_pages.representation_id == (
            representation.representation_id
        )

        assert tuple(
            (
                item.page_number,
                item.content_hash,
            )
            for item in decoded_pages.pages
        ) == tuple(
            (
                page_number,
                content_hash,
            )
            for (
                page_number,
                _start,
                _end,
                content_hash,
            ) in original_pages
        )

        structure_payload = (
            app.protected_content.load_payload(
                by_kind[
                    STRUCTURE_MAP_SEMANTIC_KIND
                ].protected_payload_id
            )
        )

        decoded_structures = (
            decode_representation_structure_map_semantics(
                structure_payload
            )
        )

        assert decoded_structures.representation_id == (
            representation.representation_id
        )

        assert tuple(
            (
                item.structure_id,
                item.structure_index,
                item.path,
                item.content_hash,
                item.metadata_json,
            )
            for item in decoded_structures.structures
        ) == tuple(
            (
                structure_id,
                structure_index,
                path,
                content_hash,
                metadata_json,
            )
            for (
                structure_id,
                structure_index,
                _structure_type,
                path,
                _parent_id,
                _start,
                _end,
                content_hash,
                metadata_json,
            ) in original_structures
        )

    finally:
        app.stop()


def test_map_cutover_is_idempotent_without_new_ciphertext(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"map-idempotent-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        calls: list[bytes] = []

        writer = _writer(
            app,
            scope.protection_scope_id,
            calls=calls,
        )

        with app.database.write_transaction() as connection:
            first = (
                repository
                .protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
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
                .protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )
            )

        assert second == first
        assert len(calls) == 2

        assert int(
            app.database.connection.execute(
                "SELECT COUNT(*) FROM protected_payloads"
            ).fetchone()[0]
        ) == payload_count

    finally:
        app.stop()


def test_structure_failure_rolls_back_page_payload_mapping_and_neutralization(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        original_pages, original_structures = _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"map-rollback-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        before_payloads = int(
            app.database.connection.execute(
                "SELECT COUNT(*) FROM protected_payloads"
            ).fetchone()[0]
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER
                test_fail_structure_semantic_mapping
                BEFORE INSERT ON
                    source_protected_semantic_payloads
                WHEN NEW.semantic_kind =
                    'source_representation_structures'
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'synthetic structure semantic failure'
                    );
                END
                """
            )

        try:
            with pytest.raises(
                SourceProtectedSemanticIntegrityError,
                match="violates the v39 schema",
            ):
                with (
                    app.database.write_transaction()
                    as connection
                ):
                    (
                        repository
                        .protect_representation_map_semantics(
                            connection,
                            source_id=source.source_id,
                            representation_id=(
                                representation
                                .representation_id
                            ),
                            protection_scope_id=(
                                scope.protection_scope_id
                            ),
                            payload_writer=_writer(
                                app,
                                scope.protection_scope_id,
                            ),
                        )
                    )

        finally:
            with app.database.write_transaction() as connection:
                connection.execute(
                    """
                    DROP TRIGGER IF EXISTS
                    test_fail_structure_semantic_mapping
                    """
                )

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
                  AND entity_id = ?
                  AND semantic_kind IN (
                      'source_representation_pages',
                      'source_representation_structures'
                  )
                """,
                (
                    source.source_id.bytes,
                    representation.representation_id.bytes,
                ),
            ).fetchone()[0]
        ) == 0

        pages = _public_pages(
            app,
            representation.representation_id,
        )

        assert tuple(
            bytes(row["content_hash"])
            for row in pages
        ) == tuple(
            item[3]
            for item in original_pages
        )

        structures = _public_structures(
            app,
            representation.representation_id,
        )

        assert tuple(
            (
                str(row["path"]),
                bytes(row["content_hash"]),
                str(row["metadata_json"]),
            )
            for row in structures
        ) == tuple(
            (
                item[3],
                item[7],
                item[8],
            )
            for item in original_structures
        )

    finally:
        app.stop()


def test_mixed_page_state_after_mapping_fails_closed(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        original_pages, _structures = _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"mixed-page-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        writer = _writer(
            app,
            scope.protection_scope_id,
        )

        with app.database.write_transaction() as connection:
            repository.protect_representation_map_semantics(
                connection,
                source_id=source.source_id,
                representation_id=(
                    representation.representation_id
                ),
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE source_representation_pages
                SET content_hash = ?
                WHERE representation_id = ?
                  AND page_number = 1
                """,
                (
                    original_pages[0][3],
                    representation.representation_id.bytes,
                ),
            )

        with pytest.raises(
            SourceProtectedSemanticIntegrityError,
            match="page map is not fully neutralized",
        ):
            with app.database.write_transaction() as connection:
                repository.protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )

    finally:
        app.stop()


def test_mixed_structure_state_after_mapping_fails_closed(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        _pages, original_structures = _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"mixed-structure-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        writer = _writer(
            app,
            scope.protection_scope_id,
        )

        with app.database.write_transaction() as connection:
            repository.protect_representation_map_semantics(
                connection,
                source_id=source.source_id,
                representation_id=(
                    representation.representation_id
                ),
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=writer,
            )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE source_representation_structures
                SET path = ?
                WHERE structure_id = ?
                """,
                (
                    original_structures[0][3],
                    original_structures[0][0].bytes,
                ),
            )

        with pytest.raises(
            SourceProtectedSemanticIntegrityError,
            match="structure map is not fully neutralized",
        ):
            with app.database.write_transaction() as connection:
                repository.protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=writer,
                )

    finally:
        app.stop()


def test_map_cutover_rejects_wrong_source_before_encrypting(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        _source, representation = _representation(
            app,
            tmp_path,
        )

        _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"wrong-map-source-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        calls: list[bytes] = []

        with pytest.raises(
            SourceProtectedSemanticIntegrityError,
            match="does not belong",
        ):
            with app.database.write_transaction() as connection:
                repository.protect_representation_map_semantics(
                    connection,
                    source_id=uuid.uuid4(),
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                        calls=calls,
                    ),
                )

        assert calls == []

    finally:
        app.stop()


def test_map_cutover_with_no_maps_is_a_clean_noop(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        scope = _scope(
            app,
            password=b"empty-map-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        calls: list[bytes] = []

        with app.database.write_transaction() as connection:
            mappings = (
                repository
                .protect_representation_map_semantics(
                    connection,
                    source_id=source.source_id,
                    representation_id=(
                        representation.representation_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                        calls=calls,
                    ),
                )
            )

        assert mappings == ()
        assert calls == []

    finally:
        app.stop()


def test_map_cutover_requires_active_transaction(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")

    try:
        source, representation = _representation(
            app,
            tmp_path,
        )

        _install_maps(
            app,
            representation.representation_id,
        )

        scope = _scope(
            app,
            password=b"map-transaction-password",
        )

        repository = SourceProtectedSemanticRepository(
            app.database
        )

        with pytest.raises(
            RuntimeError,
            match="requires an active transaction",
        ):
            repository.protect_representation_map_semantics(
                app.database.connection,
                source_id=source.source_id,
                representation_id=(
                    representation.representation_id
                ),
                protection_scope_id=(
                    scope.protection_scope_id
                ),
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )

    finally:
        app.stop()
