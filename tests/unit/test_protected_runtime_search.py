from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import athena.retrieval.protected_source as protected_source
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.retrieval.protected_source import (
    ProtectedRuntimeContextIntegrityError,
    ProtectedRuntimeSearchIntegrityError,
    ProtectedRuntimeUnsupportedSourceError,
)
from athena.security.models import Argon2idParameters
from athena.security.service import ProtectionScopeLockedError

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(
    tmp_path: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )
    app.start()
    return app


def _initialize(
    app: AthenaApplication,
    password: bytes,
) -> None:
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )


def _scope(
    app: AthenaApplication,
    password: bytes,
    *,
    label: str,
) -> uuid.UUID:
    scope = app.protected_content.create_scope(
        password,
        neutral_label=label,
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope.protection_scope_id


def _scan_absent(
    root: Path,
    *needles: bytes,
) -> None:
    scanned = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        data = path.read_bytes()
        scanned += 1

        for needle in needles:
            assert needle not in data, path

    assert scanned > 0


def test_locked_protected_scope_is_not_implicitly_searchable(
    tmp_path: Path,
) -> None:
    password = b"runtime-locked-password"
    canary = b"ATHENA_RUNTIME_LOCKED_CANARY_A17F"

    source_path = (
        tmp_path
        / "locked-secret.txt"
    )
    source_path.write_bytes(
        canary
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="locked-runtime",
        )

        app.sources.capture_protected_file(
            source_path,
            protection_scope_id=scope_id,
        )

        app.protected_content.lock_scope(
            scope_id
        )

        assert app.protected_source_search.search(
            "ATHENA_RUNTIME_LOCKED_CANARY_A17F"
        ) == ()

        with pytest.raises(
            ProtectionScopeLockedError
        ):
            app.protected_source_search.search(
                "ATHENA_RUNTIME_LOCKED_CANARY_A17F",
                protection_scope_ids=frozenset(
                    {scope_id}
                ),
            )

    finally:
        app.stop()

    _scan_absent(
        app.paths.local_root,
        canary,
        password,
        source_path.name.encode("ascii"),
        source_path.resolve().as_uri().encode("ascii"),
    )


def test_unlocked_search_and_context_are_runtime_only(
    tmp_path: Path,
) -> None:
    password = b"runtime-search-password"
    canary_text = (
        "ATHENA_RUNTIME_SEARCH_CANARY_C91E "
        "Berlin protected runtime evidence."
    )
    canary = canary_text.encode(
        "utf-8"
    )

    source_path = (
        tmp_path
        / "ATHENA_RUNTIME_METADATA_C91E.txt"
    )
    source_path.write_bytes(
        canary
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="runtime-search",
        )

        captured = app.sources.capture_protected_file(
            source_path,
            protection_scope_id=scope_id,
        )

        before_commit = int(
            app.database.connection.execute(
                """
                SELECT COALESCE(MAX(commit_seq), 0)
                FROM commit_records
                """
            ).fetchone()[0]
        )

        results = app.protected_source_search.search(
            "Berlin C91E",
            protection_scope_ids=frozenset(
                {scope_id}
            ),
        )

        assert len(
            results
        ) == 1

        result = results[0]

        assert result.source_id == captured.source.source_id
        assert result.protection_scope_id == scope_id
        assert result.source_name == source_path.name
        assert result.source_uri == source_path.resolve().as_uri()
        assert canary_text in result.text
        assert set(result.matched_terms) == {
            "berlin",
            "c91e",
        }

        bundle = (
            app.protected_source_context_builder
            .build_from_search(
                query="What does Berlin evidence say?",
                results=results,
                max_estimated_tokens=1200,
                max_items=4,
            )
        )

        assert len(
            bundle.items
        ) == 1

        assert (
            bundle.items[0].source_id
            == captured.source.source_id
        )

        assert canary_text in bundle.rendered_text
        assert (
            source_path.resolve().as_uri()
            not in bundle.rendered_text
        )

        (
            app.protected_source_context_builder
            .verify_bundle(
                bundle
            )
        )

        after_commit = int(
            app.database.connection.execute(
                """
                SELECT COALESCE(MAX(commit_seq), 0)
                FROM commit_records
                """
            ).fetchone()[0]
        )

        assert after_commit == before_commit

        assert app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_representations
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()[0] == 0

        assert app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_anchors
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()[0] == 0

        with app.source_chunk_store.connect() as connection:
            assert connection.execute(
                """
                SELECT COUNT(*)
                FROM source_chunks
                WHERE source_id = ?
                """,
                (
                    captured.source.source_id.bytes,
                ),
            ).fetchone()[0] == 0

        app.protected_content.lock_scope(
            scope_id
        )

        with pytest.raises(
            ProtectionScopeLockedError
        ):
            (
                app.protected_source_context_builder
                .verify_bundle(
                    bundle
                )
            )

    finally:
        app.stop()

    _scan_absent(
        app.paths.local_root,
        canary,
        password,
        source_path.name.encode("ascii"),
        source_path.resolve().as_uri().encode("ascii"),
    )


def test_scope_filter_never_crosses_unlocked_protection_scopes(
    tmp_path: Path,
) -> None:
    password = b"runtime-scope-filter-password"

    first_path = (
        tmp_path
        / "first.txt"
    )
    second_path = (
        tmp_path
        / "second.txt"
    )

    first_path.write_text(
        "ATHENA_SCOPE_FILTER sharedword FIRST_ONLY",
        encoding="utf-8",
    )
    second_path.write_text(
        "ATHENA_SCOPE_FILTER sharedword SECOND_ONLY",
        encoding="utf-8",
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        first_scope = _scope(
            app,
            password,
            label="scope-first",
        )

        second_scope = _scope(
            app,
            password,
            label="scope-second",
        )

        first = app.sources.capture_protected_file(
            first_path,
            protection_scope_id=first_scope,
        )
        second = app.sources.capture_protected_file(
            second_path,
            protection_scope_id=second_scope,
        )

        first_results = app.protected_source_search.search(
            "sharedword",
            protection_scope_ids=frozenset(
                {first_scope}
            ),
        )

        assert {
            item.source_id
            for item in first_results
        } == {
            first.source.source_id
        }

        assert second.source.source_id not in {
            item.source_id
            for item in first_results
        }

        app.protected_content.lock_scope(
            second_scope
        )

        implicit_results = app.protected_source_search.search(
            "sharedword"
        )

        assert {
            item.source_id
            for item in implicit_results
        } == {
            first.source.source_id
        }

    finally:
        app.stop()


def test_tampered_ephemeral_search_and_context_fail_closed(
    tmp_path: Path,
) -> None:
    password = b"runtime-integrity-password"

    source_path = (
        tmp_path
        / "integrity.txt"
    )

    source_path.write_text(
        "ATHENA_RUNTIME_INTEGRITY_44F1 evidence",
        encoding="utf-8",
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="runtime-integrity",
        )

        app.sources.capture_protected_file(
            source_path,
            protection_scope_id=scope_id,
        )

        result = app.protected_source_search.search(
            "44F1",
            protection_scope_ids=frozenset(
                {scope_id}
            ),
        )[0]

        tampered_result = replace(
            result,
            text=(
                result.text
                + " injected"
            ),
        )

        with pytest.raises(
            ProtectedRuntimeSearchIntegrityError
        ):
            app.protected_source_search.verify_result(
                tampered_result
            )

        bundle = (
            app.protected_source_context_builder
            .build_from_search(
                query="44F1",
                results=(result,),
            )
        )

        tampered_item = replace(
            bundle.items[0],
            text=(
                bundle.items[0].text
                + " injected"
            ),
        )

        tampered_bundle = replace(
            bundle,
            items=(tampered_item,),
        )

        with pytest.raises(
            ProtectedRuntimeContextIntegrityError
        ):
            (
                app.protected_source_context_builder
                .verify_bundle(
                    tampered_bundle
                )
            )

    finally:
        app.stop()


def test_normal_persistent_archive_search_never_returns_protected_source(
    tmp_path: Path,
) -> None:
    password = b"runtime-persistent-exclusion-password"

    source_path = (
        tmp_path
        / "persistent-exclusion.txt"
    )

    source_path.write_text(
        "ATHENA_PERSISTENT_EXCLUSION_2DB9",
        encoding="utf-8",
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="persistent-exclusion",
        )

        captured = app.sources.capture_protected_file(
            source_path,
            protection_scope_id=scope_id,
        )

        assert app.protected_source_search.search(
            "2DB9",
            protection_scope_ids=frozenset(
                {scope_id}
            ),
        )

        assert app.archive_search.rebuild() == 0

        assert app.archive_search.search(
            "2DB9"
        ) == ()

        assert app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_representations
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()[0] == 0

    finally:
        app.stop()


def test_unsupported_protected_document_fails_instead_of_false_complete(
    tmp_path: Path,
) -> None:
    password = b"runtime-unsupported-password"

    source_path = (
        tmp_path
        / "unsupported.bin"
    )

    source_path.write_bytes(
        b"ATHENA_UNKNOWN_BINARY_FORMAT_31F2\x00\x01"
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="runtime-unsupported",
        )

        app.sources.capture_protected_file(
            source_path,
            protection_scope_id=scope_id,
        )

        with pytest.raises(
            ProtectedRuntimeUnsupportedSourceError,
            match="TXT/Markdown/PDF/DOCX/HTML",
        ):
            app.protected_source_search.search(
                "31F2",
                protection_scope_ids=frozenset(
                    {
                        scope_id
                    }
                ),
            )

    finally:
        app.stop()


def _runtime_native_text_pdf(
    pages: tuple[str, ...],
) -> bytes:
    font_id = (
        3
        + (2 * len(pages))
    )

    objects: dict[
        int,
        bytes,
    ] = {
        1: (
            b"<< /Type /Catalog /Pages 2 0 R >>"
        ),
        2: (
            (
                "<< /Type /Pages /Kids ["
                + " ".join(
                    f"{3 + 2 * index} 0 R"
                    for index
                    in range(len(pages))
                )
                + "] /Count "
                + str(len(pages))
                + " >>"
            ).encode(
                "ascii"
            )
        ),
        font_id: (
            b"<< /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >>"
        ),
    }

    for index, page_text in enumerate(
        pages
    ):
        page_id = (
            3
            + (2 * index)
        )
        content_id = (
            page_id + 1
        )

        escaped = (
            page_text
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                "(",
                "\\(",
            )
            .replace(
                ")",
                "\\)",
            )
        )

        stream = (
            "BT /F1 12 Tf 72 720 Td "
            f"({escaped}) Tj ET"
        ).encode(
            "latin-1"
        )

        objects[page_id] = (
            (
                "<< /Type /Page /Parent 2 0 R "
                "/MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 "
                f"{font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode(
                "ascii"
            )
        )

        objects[content_id] = (
            (
                f"<< /Length {len(stream)} >>\n"
                "stream\n"
            ).encode(
                "ascii"
            )
            + stream
            + b"\nendstream"
        )

    highest = max(
        objects
    )

    output = bytearray(
        b"%PDF-1.4\n%ATHENA\n"
    )

    offsets = [
        0
    ] * (
        highest + 1
    )

    for object_id in range(
        1,
        highest + 1,
    ):
        offsets[object_id] = len(
            output
        )

        output.extend(
            f"{object_id} 0 obj\n".encode(
                "ascii"
            )
        )

        output.extend(
            objects[object_id]
        )

        output.extend(
            b"\nendobj\n"
        )

    xref = len(
        output
    )

    output.extend(
        f"xref\n0 {highest + 1}\n".encode(
            "ascii"
        )
    )

    output.extend(
        b"0000000000 65535 f \n"
    )

    for object_id in range(
        1,
        highest + 1,
    ):
        output.extend(
            (
                f"{offsets[object_id]:010d} "
                "00000 n \n"
            ).encode(
                "ascii"
            )
        )

    output.extend(
        (
            "trailer\n"
            f"<< /Size {highest + 1} "
            "/Root 1 0 R >>\n"
            "startxref\n"
            f"{xref}\n"
            "%%EOF\n"
        ).encode(
            "ascii"
        )
    )

    return bytes(
        output
    )


_RUNTIME_DOCX_W = (
    "http://schemas.openxmlformats.org/"
    "wordprocessingml/2006/main"
)

_RUNTIME_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/'
    'package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml"/>'
    "</Types>"
)


def _runtime_docx_bytes(
    value: str,
) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{_RUNTIME_DOCX_W}">'
        "<w:body>"
        "<w:p><w:r><w:t>"
        + value
        + "</w:t></w:r></w:p>"
        "<w:sectPr/>"
        "</w:body>"
        "</w:document>"
    )

    output = io.BytesIO()

    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:

        for name, payload in (
            (
                "[Content_Types].xml",
                _RUNTIME_DOCX_CONTENT_TYPES,
            ),
            (
                "word/document.xml",
                document,
            ),
        ):
            info = zipfile.ZipInfo(
                name,
                date_time=(
                    2020,
                    1,
                    1,
                    0,
                    0,
                    0,
                ),
            )

            info.compress_type = (
                zipfile.ZIP_DEFLATED
            )

            archive.writestr(
                info,
                payload.encode(
                    "utf-8"
                ),
            )

    return output.getvalue()


def _assert_no_13c2_plaintext(
    root: Path,
    *needles: bytes,
) -> None:
    for path in root.rglob(
        "*"
    ):
        if not path.is_file():
            continue

        try:
            payload = path.read_bytes()

        except OSError as exc:
            raise AssertionError(
                f"Cannot inspect persistence path: {path}"
            ) from exc

        for needle in needles:
            assert needle not in payload, (
                f"Persistent plaintext leak in {path}: "
                f"{needle!r}"
            )


def test_protected_pdf_docx_html_runtime_search_is_memory_only(
    tmp_path: Path,
) -> None:
    password = (
        b"runtime-documents-password"
    )

    pdf_token = (
        "PDFRUNTIME91A2"
    )
    docx_token = (
        "DOCXRUNTIME82B3"
    )
    html_token = (
        "HTMLRUNTIME73C4"
    )
    hidden_html_token = (
        "HTMLHIDDEN64D5"
    )

    pdf_path = (
        tmp_path
        / "protected-runtime.pdf"
    )

    docx_path = (
        tmp_path
        / "protected-runtime.docx"
    )

    html_path = (
        tmp_path
        / "protected-runtime.html"
    )

    pdf_path.write_bytes(
        _runtime_native_text_pdf(
            (
                (
                    f"{pdf_token} "
                    "ATHENA_PROTECTED_PDF_CANARY_91A2 "
                    "Berlin PDF evidence"
                ),
            )
        )
    )

    docx_path.write_bytes(
        _runtime_docx_bytes(
            (
                f"{docx_token} "
                "ATHENA_PROTECTED_DOCX_CANARY_82B3 "
                "Berlin DOCX evidence"
            )
        )
    )

    html_path.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<head>"
            '<meta charset="utf-8">'
            "<title>Protected Runtime HTML</title>"
            f"<script>{hidden_html_token}</script>"
            "</head>"
            "<body><main>"
            f"<p>{html_token} "
            "ATHENA_PROTECTED_HTML_CANARY_73C4 "
            "Berlin HTML evidence</p>"
            "</main></body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    app = _app(
        tmp_path
    )

    local_root = (
        app.paths.local_root
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="runtime-documents",
        )

        pdf_source = (
            app.sources.capture_protected_file(
                pdf_path,
                protection_scope_id=scope_id,
            )
        )

        docx_source = (
            app.sources.capture_protected_file(
                docx_path,
                protection_scope_id=scope_id,
            )
        )

        html_source = (
            app.sources.capture_protected_file(
                html_path,
                protection_scope_id=scope_id,
            )
        )

        before_total_changes = (
            app.database.connection.total_changes
        )

        expected = (
            (
                pdf_token,
                pdf_source.source.source_id,
            ),
            (
                docx_token,
                docx_source.source.source_id,
            ),
            (
                html_token,
                html_source.source.source_id,
            ),
        )

        bundles = []

        for (
            query,
            expected_source_id,
        ) in expected:

            results = (
                app.protected_source_search.search(
                    query,
                    protection_scope_ids=frozenset(
                        {
                            scope_id
                        }
                    ),
                )
            )

            assert results

            assert {
                item.source_id
                for item in results
            } == {
                expected_source_id
            }

            bundle = (
                app.protected_source_context_builder
                .build_from_search(
                    query=query,
                    results=results,
                    max_estimated_tokens=1200,
                    max_items=4,
                )
            )

            assert bundle.items

            assert {
                item.source_id
                for item in bundle.items
            } == {
                expected_source_id
            }

            assert query in (
                bundle.rendered_text
            )

            (
                app.protected_source_context_builder
                .verify_bundle(
                    bundle
                )
            )

            bundles.append(
                bundle
            )

        assert (
            app.protected_source_search.search(
                hidden_html_token,
                protection_scope_ids=frozenset(
                    {
                        scope_id
                    }
                ),
            )
            == ()
        )

        assert (
            app.database.connection.total_changes
            == before_total_changes
        )

        protected_ids = (
            pdf_source.source.source_id,
            docx_source.source.source_id,
            html_source.source.source_id,
        )

        for source_id in protected_ids:

            representation_count = int(
                app.database.connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM source_representations
                    WHERE source_id = ?
                    """,
                    (
                        source_id.bytes,
                    ),
                ).fetchone()[0]
            )

            anchor_count = int(
                app.database.connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM source_anchors
                    WHERE source_id = ?
                    """,
                    (
                        source_id.bytes,
                    ),
                ).fetchone()[0]
            )

            assert representation_count == 0
            assert anchor_count == 0

        with (
            app.source_chunk_store.connect()
            as connection
        ):
            for source_id in protected_ids:

                chunk_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM source_chunks
                        WHERE source_id = ?
                        """,
                        (
                            source_id.bytes,
                        ),
                    ).fetchone()[0]
                )

                assert chunk_count == 0

        assert not [
            path
            for path
            in local_root.rglob(
                "*.partial"
            )
            if path.is_file()
        ]

        app.protected_content.lock_scope(
            scope_id
        )

        for bundle in bundles:

            with pytest.raises(
                ProtectionScopeLockedError
            ):
                (
                    app.protected_source_context_builder
                    .verify_bundle(
                        bundle
                    )
                )

    finally:
        app.stop()

    _assert_no_13c2_plaintext(
        local_root,
        password,
        pdf_token.encode(
            "ascii"
        ),
        docx_token.encode(
            "ascii"
        ),
        html_token.encode(
            "ascii"
        ),
        hidden_html_token.encode(
            "ascii"
        ),
        pdf_path.name.encode(
            "ascii"
        ),
        docx_path.name.encode(
            "ascii"
        ),
        html_path.name.encode(
            "ascii"
        ),
        pdf_path.resolve().as_uri().encode(
            "ascii"
        ),
        docx_path.resolve().as_uri().encode(
            "ascii"
        ),
        html_path.resolve().as_uri().encode(
            "ascii"
        ),
    )


def test_protected_web_snapshot_runtime_uses_primary_article_mode(
    tmp_path: Path,
) -> None:
    password = (
        b"runtime-web-password"
    )

    article_token = (
        "WEBARTICLE7F31"
    )
    navigation_token = (
        "WEBNAV8E42"
    )
    unrelated_token = (
        "WEBUNRELATED9D53"
    )

    source_uri = (
        "https://example.test/"
        "ATHENA_PROTECTED_WEB_URI_7F31"
    )

    path = (
        tmp_path
        / "protected-web-runtime.html"
    )

    path.write_text(
        (
            "<!doctype html>"
            "<html>"
            "<head>"
            '<meta charset="utf-8">'
            "<title>Protected Article</title>"
            "</head>"
            "<body>"
            "<header><nav>"
            f"{navigation_token}"
            "</nav></header>"
            "<main>"
            '<article id="primary-story">'
            "<h1>Protected Article</h1>"
            f"<p>{article_token} "
            "ATHENA_WEB_ARTICLE_CANARY_7F31</p>"
            "</article>"
            '<article class="related-card">'
            "<h2>Related</h2>"
            f"<p>{unrelated_token}</p>"
            "</article>"
            "</main>"
            "</body>"
            "</html>"
        ),
        encoding="utf-8",
    )

    app = _app(
        tmp_path
    )

    local_root = (
        app.paths.local_root
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="runtime-web",
        )

        captured = (
            app.sources.capture_external_snapshot(
                path,
                source_uri=source_uri,
                original_name=path.name,
            )
        )

        protected_capture = (
            app.sources.protect_existing_source(
                captured.source.source_id,
                scope_id,
            )
        )

        assert (
            protected_capture.source.source_id
            == captured.source.source_id
        )

        article_results = (
            app.protected_source_search.search(
                article_token,
                protection_scope_ids=frozenset(
                    {
                        scope_id
                    }
                ),
            )
        )

        assert article_results

        assert {
            item.source_id
            for item in article_results
        } == {
            captured.source.source_id
        }

        assert (
            app.protected_source_search.search(
                navigation_token,
                protection_scope_ids=frozenset(
                    {
                        scope_id
                    }
                ),
            )
            == ()
        )

        assert (
            app.protected_source_search.search(
                unrelated_token,
                protection_scope_ids=frozenset(
                    {
                        scope_id
                    }
                ),
            )
            == ()
        )

    finally:
        app.stop()

    _assert_no_13c2_plaintext(
        local_root,
        password,
        article_token.encode(
            "ascii"
        ),
        navigation_token.encode(
            "ascii"
        ),
        unrelated_token.encode(
            "ascii"
        ),
        source_uri.encode(
            "ascii"
        ),
        path.name.encode(
            "ascii"
        ),
    )

def test_protected_pdf_input_limit_precedes_plaintext_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import athena.retrieval.protected_source as protected_source_module
    from athena.retrieval.protected_source import (
        ProtectedRuntimeSearchError,
    )
    from athena.source.pdf_parser import (
        PdfParserPolicy,
    )

    password = (
        b"protected-pdf-limit-password"
    )

    pdf_path = (
        tmp_path
        / "protected-limit.pdf"
    )

    pdf_path.write_bytes(
        _runtime_native_text_pdf(
            (
                "Protected PDF size-limit evidence",
            )
        )
    )

    app = _app(
        tmp_path
    )

    try:
        _initialize(
            app,
            password,
        )

        scope_id = _scope(
            app,
            password,
            label="protected-pdf-limit",
        )

        captured = (
            app.sources.capture_protected_file(
                pdf_path,
                protection_scope_id=scope_id,
            )
        )

        monkeypatch.setattr(
            protected_source_module,
            "DEFAULT_PDF_PARSER_POLICY",
            PdfParserPolicy(
                max_input_bytes=1
            ),
        )

        read_called = False

        def forbidden_plaintext_read(
            source_id: uuid.UUID,
        ) -> bytes:
            nonlocal read_called

            read_called = True

            raise AssertionError(
                "Protected plaintext was read "
                "before the PDF size limit."
            )

        monkeypatch.setattr(
            app.sources,
            "read_protected_bytes",
            forbidden_plaintext_read,
        )

        with pytest.raises(
            ProtectedRuntimeSearchError,
            match="input byte limit",
        ):
            app.protected_source_search.load_document(
                captured.source.source_id,
                expected_scope_id=scope_id,
            )

        assert not read_called

    finally:
        app.stop()


def test_runtime_search_does_not_materialize_all_matching_results() -> None:
    scope_id = uuid.uuid4()
    source_id = uuid.uuid4()

    source = SimpleNamespace(
        source_id=source_id,
        protection_scope_id=scope_id,
        lifecycle_state=protected_source.SourceLifecycleState.READY,
    )

    class FakeProtectedContent:
        context = SimpleNamespace(
            unlocked_protection_scopes=frozenset({scope_id})
        )

        def is_unlocked(self, protection_scope_id: uuid.UUID) -> bool:
            return protection_scope_id == scope_id

    class FakeRepository:
        def list_protected_in_scopes(self, protection_scope_ids, *, limit):
            return ((source, None),)

    service = protected_source.ProtectedRuntimeSourceSearchService(
        protected_content=FakeProtectedContent(),
        sources=object(),
        repository=FakeRepository(),
    )

    document = protected_source._RuntimeDocument(
        source_id=source_id,
        protection_scope_id=scope_id,
        source_name="synthetic.txt",
        source_uri="synthetic://a08",
        mime_type="text/plain",
        text=("needle " * 100_000),
        document_hash=b"\x01" * 32,
    )

    service.load_document = lambda source_id, expected_scope_id=None: document

    original_result = protected_source.ProtectedRuntimeSearchResult
    constructed = 0

    def counted_result(**kwargs):
        nonlocal constructed
        constructed += 1
        return original_result(**kwargs)

    protected_source.ProtectedRuntimeSearchResult = counted_result

    try:
        results = service.search(
            "needle",
            protection_scope_ids=frozenset({scope_id}),
            limit=8,
        )
    finally:
        protected_source.ProtectedRuntimeSearchResult = original_result

    assert len(results) == 8
    assert constructed == 8


def test_runtime_search_fails_closed_when_scan_capacity_is_exceeded() -> None:
    scope_id = uuid.uuid4()
    source_id = uuid.uuid4()

    source = SimpleNamespace(
        source_id=source_id,
        protection_scope_id=scope_id,
        lifecycle_state=protected_source.SourceLifecycleState.READY,
    )

    class FakeProtectedContent:
        context = SimpleNamespace(
            unlocked_protection_scopes=frozenset({scope_id})
        )

        def is_unlocked(self, protection_scope_id: uuid.UUID) -> bool:
            return protection_scope_id == scope_id

    class FakeRepository:
        def list_protected_in_scopes(self, protection_scope_ids, *, limit):
            return ((source, None),)

    service = protected_source.ProtectedRuntimeSourceSearchService(
        protected_content=FakeProtectedContent(),
        sources=object(),
        repository=FakeRepository(),
        max_scanned_chars=100,
    )

    document = protected_source._RuntimeDocument(
        source_id=source_id,
        protection_scope_id=scope_id,
        source_name="oversized.txt",
        source_uri="synthetic://capacity",
        mime_type="text/plain",
        text="needle " * 100,
        document_hash=b"\x01" * 32,
    )

    service.load_document = lambda source_id, expected_scope_id=None: document

    with pytest.raises(
        protected_source.ProtectedRuntimeSearchCapacityError
    ):
        service.search(
            "needle",
            protection_scope_ids=frozenset({scope_id}),
            limit=8,
        )
