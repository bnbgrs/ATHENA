from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.repository import (
    JobSourceProtectionFenceError,
    _job_source_dependency_ids,
    _require_unprotected_job_dependencies,
)
from athena.security.models import Argon2idParameters
from athena.source.protection_transition import (
    SourceProtectionTransitionState,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(
    local_root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=local_root,
        )
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

    scope = (
        app.protected_content.create_scope(
            password,
            neutral_label=(
                "job-fence-test"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def test_job_create_blocks_pending_and_protected_source_dependencies(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    pending_path = (
        tmp_path
        / "pending-source.txt"
    )

    protected_path = (
        tmp_path
        / "protected-source.txt"
    )

    pending_path.write_bytes(
        b"ATHENA_JOB_FENCE_PENDING_8E31"
    )

    protected_path.write_bytes(
        b"ATHENA_JOB_FENCE_PROTECTED_7C42"
    )

    app = _app(
        runtime
    )

    try:
        scope = _scope(
            app,
            password=(
                b"job-fence-password"
            ),
        )

        pending = (
            app.sources.capture_file(
                pending_path
            )
        )

        transition = (
            app.source_protection_repository.begin(
                source_id=(
                    pending.source.source_id
                ),
                protection_scope_id=(
                    scope.protection_scope_id
                ),
            )
        )

        assert (
            transition.state
            is SourceProtectionTransitionState.PENDING
        )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            app.jobs.create(
                job_type="source.process",
                requested_scope={
                    "source_id": str(
                        pending.source.source_id
                    ),
                },
            )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            app.jobs.create(
                job_type="research.exhaustive",
                requested_scope={
                    "explicit_source_ids": [
                        str(
                            pending.source.source_id
                        )
                    ],
                },
            )

        captured_protected = (
            app.sources.capture_file(
                protected_path
            )
        )

        protected = (
            app.sources.protect_existing_source(
                captured_protected.source.source_id,
                scope.protection_scope_id,
            )
        )

        assert (
            protected.source.protection_scope_id
            == scope.protection_scope_id
        )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            app.jobs.create(
                job_type="source.process",
                requested_scope={
                    "source_id": str(
                        captured_protected.source.source_id
                    ),
                },
            )

        # Jobs without Source dependencies remain
        # unaffected by the fence.
        unrelated = app.jobs.create(
            job_type="embedding.rebuild",
            requested_scope={
                "index_kind": "local",
            },
        )

        assert unrelated.job_type == (
            "embedding.rebuild"
        )

    finally:
        app.stop()


def test_indirect_representation_and_analysis_dependencies_are_resolved() -> None:
    connection = sqlite3.connect(
        ":memory:"
    )

    connection.row_factory = (
        sqlite3.Row
    )

    try:
        connection.executescript(
            """
            CREATE TABLE source_representations (
                representation_id BLOB PRIMARY KEY,
                source_id BLOB NOT NULL
            );

            CREATE TABLE source_analyses (
                analysis_id BLOB PRIMARY KEY,
                source_id BLOB NOT NULL
            );

            CREATE TABLE source_protection_transitions (
                source_id BLOB PRIMARY KEY
            );

            CREATE TABLE protected_sources (
                source_id BLOB PRIMARY KEY
            );
            """
        )

        source_id = uuid.uuid4()
        protected_source_id = (
            uuid.uuid4()
        )

        representation_id = (
            uuid.uuid4()
        )

        analysis_id = uuid.uuid4()

        connection.execute(
            """
            INSERT INTO source_representations (
                representation_id,
                source_id
            ) VALUES (?, ?)
            """,
            (
                representation_id.bytes,
                source_id.bytes,
            ),
        )

        connection.execute(
            """
            INSERT INTO source_analyses (
                analysis_id,
                source_id
            ) VALUES (?, ?)
            """,
            (
                analysis_id.bytes,
                source_id.bytes,
            ),
        )

        connection.execute(
            """
            INSERT INTO source_protection_transitions (
                source_id
            ) VALUES (?)
            """,
            (
                source_id.bytes,
            ),
        )

        connection.execute(
            """
            INSERT INTO protected_sources (
                source_id
            ) VALUES (?)
            """,
            (
                protected_source_id.bytes,
            ),
        )

        representation_scope = (
            json.dumps(
                {
                    "representation_id": str(
                        representation_id
                    ),
                }
            )
        )

        analysis_scope = (
            json.dumps(
                {
                    "analysis_id": str(
                        analysis_id
                    ),
                }
            )
        )

        explicit_scope = (
            json.dumps(
                {
                    "explicit_source_ids": [
                        str(
                            protected_source_id
                        )
                    ],
                }
            )
        )

        representation_sources = (
            _job_source_dependency_ids(
                connection,
                representation_scope,
            )
        )

        analysis_sources = (
            _job_source_dependency_ids(
                connection,
                analysis_scope,
            )
        )

        assert representation_sources == (
            frozenset(
                {
                    source_id,
                }
            )
        )

        assert analysis_sources == (
            frozenset(
                {
                    source_id,
                }
            )
        )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            _require_unprotected_job_dependencies(
                connection,
                representation_scope,
            )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            _require_unprotected_job_dependencies(
                connection,
                analysis_scope,
            )

        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            _require_unprotected_job_dependencies(
                connection,
                explicit_scope,
            )

        free_source = uuid.uuid4()

        _require_unprotected_job_dependencies(
            connection,
            json.dumps(
                {
                    "source_id": str(
                        free_source
                    ),
                }
            ),
        )

    finally:
        connection.close()
