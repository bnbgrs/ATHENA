"""Versioned News schema and additive Core migration payloads."""

from __future__ import annotations

import hashlib
import json
import sqlite3


def _require_active_transaction(
    connection: sqlite3.Connection,
    message: str,
) -> None:
    if not connection.in_transaction:
        raise RuntimeError(message)


NEWS_SCHEMA_V1_VERSION = 1
NEWS_SCHEMA_V1_ID = "news-domain-v1"
NEWS_EVENT_SCHEMA_VERSION = 2
NEWS_EVENT_SCHEMA_ID = "news-domain-v2"
NEWS_OPERATIONAL_SCHEMA_VERSION = 3
NEWS_OPERATIONAL_SCHEMA_ID = "news-domain-v3"
NEWS_SCHEMA_VERSION = 4
NEWS_SCHEMA_ID = "news-domain-v4"


def _rollback_if_active(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        connection.execute("ROLLBACK")


def initialize_news_schema(
    connection: sqlite3.Connection,
) -> None:
    """Initialize/advance News tables for isolated tooling."""
    if connection.in_transaction:
        raise RuntimeError(
            "News schema initialization requires no active transaction."
        )

    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + _NEWS_SCHEMA_V1_SQL
            + "\nCOMMIT;"
        )

        row = connection.execute(
            """
            SELECT schema_version, schema_id
            FROM news_schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        if (
            row is not None
            and int(row["schema_version"])
            == NEWS_SCHEMA_V1_VERSION
            and str(row["schema_id"])
            == NEWS_SCHEMA_V1_ID
        ):
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + _NEWS_EVENT_STRUCTURE_V2_SQL
                + "\nCOMMIT;"
            )

        row = connection.execute(
            """
            SELECT schema_version, schema_id
            FROM news_schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        if (
            row is not None
            and int(row["schema_version"])
            == NEWS_EVENT_SCHEMA_VERSION
            and str(row["schema_id"])
            == NEWS_EVENT_SCHEMA_ID
        ):
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + _NEWS_OPERATIONAL_V3_SQL
                + "\nCOMMIT;"
            )

        row = connection.execute(
            """
            SELECT schema_version, schema_id
            FROM news_schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        if (
            row is not None
            and int(row["schema_version"])
            == NEWS_OPERATIONAL_SCHEMA_VERSION
            and str(row["schema_id"])
            == NEWS_OPERATIONAL_SCHEMA_ID
        ):
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + _NEWS_FINDING_ELIGIBILITY_V4_SQL
            )

            _require_active_transaction(
                connection,
                "News v4 initialization transaction "
                "ended before legacy backfill.",
            )

            _backfill_legacy_news_finding_assessments(
                connection
            )

            connection.execute("COMMIT")

    except BaseException:
        _rollback_if_active(connection)
        raise

    verify_news_schema_v30(connection)


def migrate_news_schema_v25_to_v26(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    migration_id: str,
) -> None:
    """Atomically add the historical v1 News domain and advance Core to v26."""
    if connection.in_transaction:
        raise RuntimeError("News schema migration requires no active transaction.")
    if schema_version != 26:
        raise RuntimeError("ATHENA News v1 migration is defined only for Core schema v26.")
    if not migration_id or "'" in migration_id:
        raise RuntimeError("ATHENA News migration id is invalid.")
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + _NEWS_SCHEMA_V1_SQL
            + f"""
UPDATE schema_metadata
SET schema_version = {schema_version},
    last_migration_id = '{migration_id}',
    minimum_reader_version = {schema_version}
WHERE singleton_id = 1;
PRAGMA user_version = {schema_version};
COMMIT;
"""
        )
    except BaseException:
        _rollback_if_active(connection)
        raise


def migrate_news_schema_v26_to_v27(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    migration_id: str,
) -> None:
    """Add structured event identity/time fields and advance Core to v27."""
    if connection.in_transaction:
        raise RuntimeError("News event-structure migration requires no active transaction.")
    if schema_version != 27:
        raise RuntimeError("ATHENA News event-structure migration is defined only for v27.")
    if not migration_id or "'" in migration_id:
        raise RuntimeError("ATHENA News event-structure migration id is invalid.")
    verify_news_schema_v26(connection)
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + _NEWS_EVENT_STRUCTURE_V2_SQL
            + f"""
UPDATE schema_metadata
SET schema_version = {schema_version},
    last_migration_id = '{migration_id}',
    minimum_reader_version = {schema_version}
WHERE singleton_id = 1;
PRAGMA user_version = {schema_version};
COMMIT;
"""
        )
    except BaseException:
        _rollback_if_active(connection)
        raise



def migrate_news_schema_v27_to_v28(
    connection: sqlite3.Connection, *, schema_version: int, migration_id: str
) -> None:
    """Add durable source cursor/dedup/ranking state and advance Core to v28."""
    if connection.in_transaction:
        raise RuntimeError("News operational migration requires no active transaction.")
    if schema_version != 28:
        raise RuntimeError("ATHENA News operational migration is defined only for v28.")
    if not migration_id or "'" in migration_id:
        raise RuntimeError("ATHENA News operational migration id is invalid.")
    verify_news_schema_v27(connection)
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n" + _NEWS_OPERATIONAL_V3_SQL + f"""
UPDATE schema_metadata
SET schema_version = {schema_version}, last_migration_id = '{migration_id}',
    minimum_reader_version = {schema_version}
WHERE singleton_id = 1;
PRAGMA user_version = {schema_version};
COMMIT;
"""
        )
    except BaseException:
        _rollback_if_active(connection)
        raise

def _backfill_legacy_news_finding_assessments(
    connection: sqlite3.Connection,
) -> None:
    """Preserve pre-v30 one-event-per-finding decisions durably."""
    event_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM news_events"
        ).fetchone()[0]
    )

    if event_count == 0:
        return

    research_results_exists = (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'research_results'
            """
        ).fetchone()
        is not None
    )

    if not research_results_exists:
        raise RuntimeError(
            "Legacy News events cannot be backfilled "
            "without ResearchResult storage."
        )

    rows = connection.execute(
        """
        SELECT
            event.run_id,
            event.event_ordinal,
            event.finding_ordinal,
            event.summary,
            event.event_time_start,
            event.event_time_end,
            event.event_time_precision,
            event.location_text,
            event.actors_json,
            event.core_action,
            event.publication_time_min_us,
            event.publication_time_max_us,
            event.retrieval_time_min_us,
            event.retrieval_time_max_us,
            event.structuring_run_id,
            event.created_at_us,
            COALESCE(
                event.research_result_id,
                run.research_result_id
            ) AS effective_research_result_id,
            result.content_json AS research_content_json
        FROM news_events AS event
        JOIN news_runs AS run
          ON run.run_id = event.run_id
        LEFT JOIN research_results AS result
          ON result.result_id = COALESCE(
              event.research_result_id,
              run.research_result_id
          )
        ORDER BY
            event.run_id,
            event.event_ordinal
        """
    ).fetchall()

    if len(rows) != event_count:
        raise RuntimeError(
            "Legacy News event backfill could not "
            "resolve every persisted event."
        )

    run_state: dict[
        bytes,
        tuple[
            bytes,
            tuple[str, ...],
            set[int],
        ],
    ] = {}

    inserts: list[tuple[object, ...]] = []

    for row in rows:
        run_id = bytes(row["run_id"])

        raw_result_id = row[
            "effective_research_result_id"
        ]
        raw_content = row[
            "research_content_json"
        ]

        if (
            raw_result_id is None
            or raw_content is None
        ):
            raise RuntimeError(
                "Legacy News event has no recoverable "
                "ResearchResult."
            )

        result_id = bytes(raw_result_id)

        if len(result_id) != 16:
            raise RuntimeError(
                "Legacy News event has invalid "
                "ResearchResult identity."
            )

        try:
            content = json.loads(
                str(raw_content)
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "Legacy News ResearchResult JSON "
                "cannot be decoded."
            ) from exc

        if not isinstance(content, dict):
            raise RuntimeError(
                "Legacy News ResearchResult payload "
                "is not an object."
            )

        raw_findings = content.get("findings")

        if (
            not isinstance(raw_findings, list)
            or any(
                not isinstance(item, str)
                for item in raw_findings
            )
        ):
            raise RuntimeError(
                "Legacy News ResearchResult findings "
                "are invalid."
            )

        findings = tuple(raw_findings)

        event_ordinal = int(
            row["event_ordinal"]
        )
        finding_ordinal = int(
            row["finding_ordinal"]
        )

        if (
            event_ordinal < 0
            or finding_ordinal != event_ordinal
            or finding_ordinal >= len(findings)
        ):
            raise RuntimeError(
                "Legacy News event/finding ordinals "
                "cannot be recovered safely."
            )

        finding = findings[
            finding_ordinal
        ]

        if str(row["summary"]) != finding:
            raise RuntimeError(
                "Legacy News event text no longer "
                "matches its Research finding."
            )

        state = run_state.get(run_id)

        if state is None:
            seen: set[int] = set()

            run_state[run_id] = (
                result_id,
                findings,
                seen,
            )
        else:
            (
                previous_result_id,
                previous_findings,
                seen,
            ) = state

            if (
                previous_result_id != result_id
                or previous_findings != findings
            ):
                raise RuntimeError(
                    "Legacy News run references "
                    "inconsistent ResearchResults."
                )

        if finding_ordinal in seen:
            raise RuntimeError(
                "Legacy News finding ordinal is duplicated."
            )

        seen.add(finding_ordinal)

        inserts.append(
            (
                run_id,
                result_id,
                finding_ordinal,
                hashlib.sha256(
                    finding.encode("utf-8")
                ).digest(),
                "event",
                "current_development",
                row["event_time_start"],
                row["event_time_end"],
                str(
                    row["event_time_precision"]
                ),
                row["location_text"],
                str(row["actors_json"]),
                row["core_action"],
                row["publication_time_min_us"],
                row["publication_time_max_us"],
                row["retrieval_time_min_us"],
                row["retrieval_time_max_us"],
                row["structuring_run_id"],
                int(row["created_at_us"]),
            )
        )

    for (
        _run_id,
        (
            _result_id,
            findings,
            seen,
        ),
    ) in run_state.items():
        if seen != set(
            range(len(findings))
        ):
            raise RuntimeError(
                "Legacy News run does not preserve "
                "the historical one-event-per-finding "
                "invariant."
            )

    connection.executemany(
        """
        INSERT INTO news_finding_assessments (
            run_id,
            research_result_id,
            finding_ordinal,
            finding_sha256,
            eligibility,
            eligibility_reason,
            event_time_start,
            event_time_end,
            event_time_precision,
            location_text,
            actors_json,
            core_action,
            publication_time_min_us,
            publication_time_max_us,
            retrieval_time_min_us,
            retrieval_time_max_us,
            structuring_run_id,
            created_at_us
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        inserts,
    )


def migrate_news_schema_v29_to_v30(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    migration_id: str,
) -> None:
    """Add durable finding eligibility and advance Core to v30."""
    if connection.in_transaction:
        raise RuntimeError(
            "News finding eligibility migration "
            "requires no active transaction."
        )

    if schema_version != 30:
        raise RuntimeError(
            "ATHENA News finding eligibility migration "
            "is defined only for Core schema v30."
        )

    if not migration_id or "'" in migration_id:
        raise RuntimeError(
            "ATHENA News finding eligibility migration id is invalid."
        )

    verify_news_schema_v28(connection)

    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + _NEWS_FINDING_ELIGIBILITY_V4_SQL
        )

        _require_active_transaction(
            connection,
            "News v30 migration transaction ended "
            "before legacy backfill.",
        )

        _backfill_legacy_news_finding_assessments(
            connection
        )

        connection.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                schema_version,
                migration_id,
                schema_version,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = {schema_version}"
        )

        connection.execute("COMMIT")

    except BaseException:
        _rollback_if_active(connection)
        raise


def _required_news_tables() -> set[str]:
    return {
        "news_schema_metadata",
        "news_profiles",
        "news_categories",
        "news_sources",
        "news_source_categories",
        "news_runs",
        "news_period_runs",
        "news_discoveries",
        "news_source_run_failures",
        "news_events",
        "news_event_links",
        "news_digests",
    }


def _verify_news_tables_and_foreign_keys(connection: sqlite3.Connection) -> None:
    actual = {
        str(item[0])
        for item in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    missing = _required_news_tables().difference(actual)
    if missing:
        raise RuntimeError(
            "ATHENA News schema is incomplete: " + ", ".join(sorted(missing))
        )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("ATHENA News schema foreign-key verification failed.")


def verify_news_schema_v26(connection: sqlite3.Connection) -> None:
    """Verify the historical v1 News domain stored in Core schema v26."""
    row = connection.execute(
        "SELECT schema_version, schema_id FROM news_schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    if (
        row is None
        or int(row["schema_version"]) != NEWS_SCHEMA_V1_VERSION
        or str(row["schema_id"]) != NEWS_SCHEMA_V1_ID
    ):
        raise RuntimeError("Unsupported ATHENA News v1 domain schema.")
    _verify_news_tables_and_foreign_keys(connection)


def verify_news_schema_v27(connection: sqlite3.Connection) -> None:
    """Verify structured News event identity/time persistence and provenance."""
    row = connection.execute(
        "SELECT schema_version, schema_id FROM news_schema_metadata WHERE singleton_id = 1"
    ).fetchone()
    if (
        row is None
        or int(row["schema_version"]) != NEWS_EVENT_SCHEMA_VERSION
        or str(row["schema_id"]) != NEWS_EVENT_SCHEMA_ID
    ):
        raise RuntimeError("Unsupported ATHENA News v2 domain schema.")
    _verify_news_tables_and_foreign_keys(connection)
    event_columns = {
        str(item[1])
        for item in connection.execute("PRAGMA table_info(news_events)").fetchall()
    }
    required_columns = {
        "event_time_start",
        "event_time_end",
        "event_time_precision",
        "location_text",
        "actors_json",
        "core_action",
        "publication_time_min_us",
        "publication_time_max_us",
        "retrieval_time_min_us",
        "retrieval_time_max_us",
        "structuring_run_id",
    }
    missing = required_columns.difference(event_columns)
    if missing:
        raise RuntimeError(
            "ATHENA structured News event schema is incomplete: "
            + ", ".join(sorted(missing))
        )



def _verify_news_operational_shape(
    connection: sqlite3.Connection,
) -> None:
    operational_tables = {
        "news_profile_categories",
        "news_source_states",
        "news_event_members",
        "news_digest_items",
    }

    actual_tables = {
        str(item[0])
        for item in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }

    missing_operational = (
        operational_tables.difference(
            actual_tables
        )
    )

    if missing_operational:
        raise RuntimeError(
            "ATHENA News operational schema is incomplete: "
            + ", ".join(
                sorted(missing_operational)
            )
        )

    _verify_news_tables_and_foreign_keys(
        connection
    )

    discovery_columns = {
        str(item[1])
        for item in connection.execute(
            "PRAGMA table_info(news_discoveries)"
        ).fetchall()
    }

    required_discovery = {
        "content_sha256",
        "dedup_state",
        "duplicate_of_discovery_id",
        "near_duplicate_score",
    }

    if not required_discovery.issubset(
        discovery_columns
    ):
        raise RuntimeError(
            "ATHENA News discovery dedup schema is incomplete."
        )

    event_columns = {
        str(item[1])
        for item in connection.execute(
            "PRAGMA table_info(news_events)"
        ).fetchall()
    }

    required_event = {
        "event_time_start",
        "event_time_end",
        "event_time_precision",
        "location_text",
        "actors_json",
        "core_action",
        "publication_time_min_us",
        "publication_time_max_us",
        "retrieval_time_min_us",
        "retrieval_time_max_us",
        "structuring_run_id",
        "first_seen_us",
        "last_updated_us",
        "importance",
        "relevance",
        "novelty",
        "source_count",
        "independent_source_count",
        "conflicting_source_count",
        "research_job_id",
        "research_result_id",
    }

    if not required_event.issubset(
        event_columns
    ):
        raise RuntimeError(
            "ATHENA News event ranking schema is incomplete."
        )


def verify_news_schema_v28(
    connection: sqlite3.Connection,
) -> None:
    """Verify completed durable News operational state."""
    row = connection.execute(
        """
        SELECT schema_version, schema_id
        FROM news_schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    if (
        row is None
        or int(row["schema_version"])
        != NEWS_OPERATIONAL_SCHEMA_VERSION
        or str(row["schema_id"])
        != NEWS_OPERATIONAL_SCHEMA_ID
    ):
        raise RuntimeError(
            "Unsupported ATHENA News v3 domain schema."
        )

    _verify_news_operational_shape(connection)


def verify_news_schema_v30(
    connection: sqlite3.Connection,
) -> None:
    """Verify durable News finding eligibility state."""
    row = connection.execute(
        """
        SELECT schema_version, schema_id
        FROM news_schema_metadata
        WHERE singleton_id = 1
        """
    ).fetchone()

    if (
        row is None
        or int(row["schema_version"])
        != NEWS_SCHEMA_VERSION
        or str(row["schema_id"])
        != NEWS_SCHEMA_ID
    ):
        raise RuntimeError(
            "Unsupported ATHENA News v4 domain schema."
        )

    _verify_news_operational_shape(connection)

    tables = {
        str(item[0])
        for item in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }

    if "news_finding_assessments" not in tables:
        raise RuntimeError(
            "ATHENA News finding assessment table is missing."
        )

    event_columns = {
        str(item[1])
        for item in connection.execute(
            "PRAGMA table_info(news_events)"
        ).fetchall()
    }

    if "finding_ordinal" not in event_columns:
        raise RuntimeError(
            "ATHENA News event/finding identity is incomplete."
        )

    if connection.execute(
        """
        SELECT 1
        FROM news_events
        WHERE finding_ordinal IS NULL
        LIMIT 1
        """
    ).fetchone() is not None:
        raise RuntimeError(
            "ATHENA News contains an event without finding identity."
        )

    indexes = {
        str(item[1])
        for item in connection.execute(
            "PRAGMA index_list(news_events)"
        ).fetchall()
    }

    if (
        "uq_news_events_run_finding_ordinal"
        not in indexes
    ):
        raise RuntimeError(
            "ATHENA News event/finding uniqueness index is missing."
        )

    assessment_columns = {
        str(item[1])
        for item in connection.execute(
            """
            PRAGMA table_info(
                news_finding_assessments
            )
            """
        ).fetchall()
    }

    required_assessment_columns = {
        "run_id",
        "research_result_id",
        "finding_ordinal",
        "finding_sha256",
        "eligibility",
        "eligibility_reason",
        "event_time_start",
        "event_time_end",
        "event_time_precision",
        "location_text",
        "actors_json",
        "core_action",
        "publication_time_min_us",
        "publication_time_max_us",
        "retrieval_time_min_us",
        "retrieval_time_max_us",
        "structuring_run_id",
        "created_at_us",
    }

    if not required_assessment_columns.issubset(
        assessment_columns
    ):
        raise RuntimeError(
            "ATHENA News finding assessment schema is incomplete."
        )

    event_without_assessment = connection.execute(
        """
        SELECT 1
        FROM news_events AS event
        LEFT JOIN news_finding_assessments AS assessment
          ON assessment.run_id = event.run_id
         AND assessment.finding_ordinal =
             event.finding_ordinal
        WHERE assessment.run_id IS NULL
           OR assessment.eligibility != 'event'
           OR (
               event.research_result_id IS NOT NULL
               AND event.research_result_id !=
                   assessment.research_result_id
           )
        LIMIT 1
        """
    ).fetchone()

    if event_without_assessment is not None:
        raise RuntimeError(
            "ATHENA News event has no matching "
            "durable event-eligibility assessment."
        )

    if connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise RuntimeError(
            "ATHENA News v4 foreign-key verification failed."
        )


_NEWS_FINDING_ELIGIBILITY_V4_SQL = """
ALTER TABLE news_events
ADD COLUMN finding_ordinal INTEGER NULL
    CHECK(
        finding_ordinal IS NULL
        OR finding_ordinal >= 0
    );

UPDATE news_events
SET finding_ordinal = event_ordinal
WHERE finding_ordinal IS NULL;

CREATE UNIQUE INDEX
    uq_news_events_run_finding_ordinal
ON news_events(
    run_id,
    finding_ordinal
);

CREATE TABLE news_finding_assessments (
    run_id BLOB(16) NOT NULL
        CHECK(length(run_id) = 16),
    research_result_id BLOB(16) NOT NULL
        CHECK(length(research_result_id) = 16),
    finding_ordinal INTEGER NOT NULL
        CHECK(finding_ordinal >= 0),
    finding_sha256 BLOB(32) NOT NULL
        CHECK(length(finding_sha256) = 32),
    eligibility TEXT NOT NULL
        CHECK(
            eligibility IN (
                'event',
                'context'
            )
        ),
    eligibility_reason TEXT NOT NULL
        CHECK(
            eligibility_reason IN (
                'current_development',
                'background',
                'static_fact',
                'historical_context',
                'analysis',
                'opinion',
                'product_description',
                'other_context'
            )
        ),
    event_time_start TEXT NULL,
    event_time_end TEXT NULL,
    event_time_precision TEXT NOT NULL
        CHECK(
            event_time_precision IN (
                'unknown',
                'instant',
                'day',
                'range'
            )
        ),
    location_text TEXT NULL,
    actors_json TEXT NOT NULL
        CHECK(json_valid(actors_json)),
    core_action TEXT NULL,
    publication_time_min_us INTEGER NULL
        CHECK(
            publication_time_min_us IS NULL
            OR publication_time_min_us >= 0
        ),
    publication_time_max_us INTEGER NULL
        CHECK(
            publication_time_max_us IS NULL
            OR publication_time_max_us >= 0
        ),
    retrieval_time_min_us INTEGER NULL
        CHECK(
            retrieval_time_min_us IS NULL
            OR retrieval_time_min_us >= 0
        ),
    retrieval_time_max_us INTEGER NULL
        CHECK(
            retrieval_time_max_us IS NULL
            OR retrieval_time_max_us >= 0
        ),
    structuring_run_id BLOB(16) NULL
        CHECK(
            structuring_run_id IS NULL
            OR length(structuring_run_id) = 16
        ),
    created_at_us INTEGER NOT NULL
        CHECK(created_at_us >= 0),

    PRIMARY KEY(
        run_id,
        finding_ordinal
    ),

    FOREIGN KEY(run_id)
        REFERENCES news_runs(run_id),

    FOREIGN KEY(research_result_id)
        REFERENCES research_results(result_id),

    FOREIGN KEY(structuring_run_id)
        REFERENCES processing_runs(
            processing_run_id
        ),

    CHECK(
        (
            eligibility = 'event'
            AND eligibility_reason =
                'current_development'
        )
        OR
        (
            eligibility = 'context'
            AND eligibility_reason !=
                'current_development'
        )
    ),

    CHECK(
        eligibility = 'event'
        OR (
            event_time_start IS NULL
            AND event_time_end IS NULL
            AND event_time_precision =
                'unknown'
            AND location_text IS NULL
            AND actors_json = '[]'
            AND core_action IS NULL
        )
    )
) WITHOUT ROWID;

CREATE INDEX
    idx_news_finding_assessments_result
ON news_finding_assessments(
    research_result_id,
    finding_ordinal
);

UPDATE news_schema_metadata
SET schema_version = 4,
    schema_id = 'news-domain-v4'
WHERE singleton_id = 1;
"""


_NEWS_OPERATIONAL_V3_SQL = """
CREATE TABLE IF NOT EXISTS news_profile_categories (
    profile_id BLOB(16) NOT NULL CHECK(length(profile_id)=16),
    category_key TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    weight REAL NOT NULL CHECK(weight >= 0.0 AND weight <= 10.0),
    PRIMARY KEY(profile_id, category_key),
    FOREIGN KEY(profile_id) REFERENCES news_profiles(profile_id),
    FOREIGN KEY(category_key) REFERENCES news_categories(category_key)
) WITHOUT ROWID;
INSERT OR IGNORE INTO news_profile_categories(profile_id, category_key, enabled, weight)
SELECT p.profile_id, c.category_key, c.enabled, c.weight
FROM news_profiles AS p CROSS JOIN news_categories AS c;

CREATE TABLE IF NOT EXISTS news_source_states (
    news_source_id BLOB(16) PRIMARY KEY CHECK(length(news_source_id)=16),
    last_attempt_at_us INTEGER NULL CHECK(last_attempt_at_us IS NULL OR last_attempt_at_us >= 0),
    last_success_at_us INTEGER NULL CHECK(last_success_at_us IS NULL OR last_success_at_us >= 0),
    last_published_at_us INTEGER NULL CHECK(last_published_at_us IS NULL OR last_published_at_us >= 0),
    last_canonical_url TEXT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    next_retry_at_us INTEGER NULL CHECK(next_retry_at_us IS NULL OR next_retry_at_us >= 0),
    last_error TEXT NULL,
    FOREIGN KEY(news_source_id) REFERENCES news_sources(news_source_id)
) WITHOUT ROWID;
INSERT OR IGNORE INTO news_source_states(news_source_id)
SELECT news_source_id FROM news_sources;

ALTER TABLE news_discoveries ADD COLUMN content_sha256 BLOB(32) NULL
    CHECK(content_sha256 IS NULL OR length(content_sha256)=32);
ALTER TABLE news_discoveries ADD COLUMN dedup_state TEXT NOT NULL DEFAULT 'unique'
    CHECK(dedup_state IN ('unique','exact_duplicate','near_duplicate'));
ALTER TABLE news_discoveries ADD COLUMN duplicate_of_discovery_id BLOB(16) NULL
    REFERENCES news_discoveries(discovery_id)
    CHECK(duplicate_of_discovery_id IS NULL OR length(duplicate_of_discovery_id)=16);
ALTER TABLE news_discoveries ADD COLUMN near_duplicate_score REAL NULL
    CHECK(near_duplicate_score IS NULL OR (near_duplicate_score >= 0.0 AND near_duplicate_score <= 1.0));
CREATE INDEX IF NOT EXISTS idx_news_discoveries_content ON news_discoveries(run_id, content_sha256)
    WHERE content_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_news_discoveries_dedup ON news_discoveries(run_id, dedup_state);

ALTER TABLE news_events ADD COLUMN first_seen_us INTEGER NULL CHECK(first_seen_us IS NULL OR first_seen_us >= 0);
ALTER TABLE news_events ADD COLUMN last_updated_us INTEGER NULL CHECK(last_updated_us IS NULL OR last_updated_us >= 0);
ALTER TABLE news_events ADD COLUMN importance REAL NOT NULL DEFAULT 0.0 CHECK(importance BETWEEN 0.0 AND 1.0);
ALTER TABLE news_events ADD COLUMN relevance REAL NOT NULL DEFAULT 0.0 CHECK(relevance BETWEEN 0.0 AND 1.0);
ALTER TABLE news_events ADD COLUMN novelty REAL NOT NULL DEFAULT 1.0 CHECK(novelty BETWEEN 0.0 AND 1.0);
ALTER TABLE news_events ADD COLUMN source_count INTEGER NOT NULL DEFAULT 0 CHECK(source_count >= 0);
ALTER TABLE news_events ADD COLUMN independent_source_count INTEGER NOT NULL DEFAULT 0 CHECK(independent_source_count >= 0);
ALTER TABLE news_events ADD COLUMN conflicting_source_count INTEGER NOT NULL DEFAULT 0 CHECK(conflicting_source_count >= 0);
ALTER TABLE news_events ADD COLUMN research_job_id BLOB(16) NULL REFERENCES jobs(job_id)
    CHECK(research_job_id IS NULL OR length(research_job_id)=16);
ALTER TABLE news_events ADD COLUMN research_result_id BLOB(16) NULL REFERENCES research_results(result_id)
    CHECK(research_result_id IS NULL OR length(research_result_id)=16);

CREATE TABLE IF NOT EXISTS news_event_members (
    event_id BLOB(16) NOT NULL CHECK(length(event_id)=16),
    source_id BLOB(16) NOT NULL CHECK(length(source_id)=16),
    membership_kind TEXT NOT NULL CHECK(membership_kind IN ('supporting','conflicting')),
    PRIMARY KEY(event_id, source_id, membership_kind),
    FOREIGN KEY(event_id) REFERENCES news_events(event_id),
    FOREIGN KEY(source_id) REFERENCES sources(source_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_digest_items (
    digest_id BLOB(16) NOT NULL CHECK(length(digest_id)=16),
    rank_no INTEGER NOT NULL CHECK(rank_no >= 1),
    event_id BLOB(16) NOT NULL CHECK(length(event_id)=16),
    importance REAL NOT NULL CHECK(importance BETWEEN 0.0 AND 1.0),
    relevance REAL NOT NULL CHECK(relevance BETWEEN 0.0 AND 1.0),
    novelty REAL NOT NULL CHECK(novelty BETWEEN 0.0 AND 1.0),
    PRIMARY KEY(digest_id, rank_no),
    UNIQUE(digest_id, event_id),
    FOREIGN KEY(digest_id) REFERENCES news_digests(digest_id),
    FOREIGN KEY(event_id) REFERENCES news_events(event_id)
) WITHOUT ROWID;

UPDATE news_schema_metadata SET schema_version = 3, schema_id = 'news-domain-v3'
WHERE singleton_id = 1;
"""

_NEWS_EVENT_STRUCTURE_V2_SQL = """
ALTER TABLE news_events ADD COLUMN event_time_start TEXT NULL;
ALTER TABLE news_events ADD COLUMN event_time_end TEXT NULL;
ALTER TABLE news_events ADD COLUMN event_time_precision TEXT NOT NULL DEFAULT 'unknown'
    CHECK(event_time_precision IN ('unknown','instant','day','range'));
ALTER TABLE news_events ADD COLUMN location_text TEXT NULL;
ALTER TABLE news_events ADD COLUMN actors_json TEXT NOT NULL DEFAULT '[]'
    CHECK(json_valid(actors_json));
ALTER TABLE news_events ADD COLUMN core_action TEXT NULL;
ALTER TABLE news_events ADD COLUMN publication_time_min_us INTEGER NULL
    CHECK(publication_time_min_us IS NULL OR publication_time_min_us >= 0);
ALTER TABLE news_events ADD COLUMN publication_time_max_us INTEGER NULL
    CHECK(publication_time_max_us IS NULL OR publication_time_max_us >= 0);
ALTER TABLE news_events ADD COLUMN retrieval_time_min_us INTEGER NULL
    CHECK(retrieval_time_min_us IS NULL OR retrieval_time_min_us >= 0);
ALTER TABLE news_events ADD COLUMN retrieval_time_max_us INTEGER NULL
    CHECK(retrieval_time_max_us IS NULL OR retrieval_time_max_us >= 0);
ALTER TABLE news_events ADD COLUMN structuring_run_id BLOB(16) NULL
    REFERENCES processing_runs(processing_run_id)
    CHECK(structuring_run_id IS NULL OR length(structuring_run_id)=16);
UPDATE news_schema_metadata
SET schema_version = 2, schema_id = 'news-domain-v2'
WHERE singleton_id = 1;
"""


_NEWS_SCHEMA_V1_SQL = """
CREATE TABLE IF NOT EXISTS news_schema_metadata (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    schema_version INTEGER NOT NULL,
    schema_id TEXT NOT NULL
);
INSERT OR IGNORE INTO news_schema_metadata VALUES (1, 1, 'news-domain-v1');

CREATE TABLE IF NOT EXISTS news_profiles (
    profile_id BLOB(16) PRIMARY KEY CHECK(length(profile_id)=16),
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    timezone_name TEXT NOT NULL,
    local_hour INTEGER NOT NULL CHECK(local_hour BETWEEN 0 AND 23),
    local_minute INTEGER NOT NULL CHECK(local_minute BETWEEN 0 AND 59),
    language_json TEXT NOT NULL CHECK(json_valid(language_json)),
    output_language TEXT NOT NULL CHECK(length(output_language) BETWEEN 2 AND 16),
    backfill_days INTEGER NOT NULL CHECK(backfill_days BETWEEN 1 AND 30),
    max_articles_per_day INTEGER NOT NULL CHECK(max_articles_per_day BETWEEN 1 AND 1000),
    max_bytes_per_day INTEGER NOT NULL CHECK(max_bytes_per_day BETWEEN 1048576 AND 2147483648),
    consent_host_hash BLOB(32) NULL CHECK(consent_host_hash IS NULL OR length(consent_host_hash)=32),
    consented_at_us INTEGER NULL,
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_categories (
    category_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    ordinal INTEGER NOT NULL UNIQUE,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    weight REAL NOT NULL CHECK(weight >= 0.0)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_sources (
    news_source_id BLOB(16) PRIMARY KEY CHECK(length(news_source_id)=16),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    source_class TEXT NOT NULL CHECK(source_class IN ('primary','mainstream','specialist','independent','alternative')),
    region TEXT NOT NULL,
    language TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    site_url TEXT NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100),
    daily_limit INTEGER NOT NULL CHECK(daily_limit BETWEEN 1 AND 100),
    perspective TEXT NOT NULL,
    independence_group TEXT NOT NULL,
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_source_categories (
    news_source_id BLOB(16) NOT NULL CHECK(length(news_source_id)=16),
    category_key TEXT NOT NULL,
    weight REAL NOT NULL CHECK(weight >= 0.0),
    PRIMARY KEY(news_source_id, category_key),
    FOREIGN KEY(news_source_id) REFERENCES news_sources(news_source_id),
    FOREIGN KEY(category_key) REFERENCES news_categories(category_key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_runs (
    run_id BLOB(16) PRIMARY KEY CHECK(length(run_id)=16),
    profile_id BLOB(16) NOT NULL CHECK(length(profile_id)=16),
    job_id BLOB(16) NOT NULL UNIQUE CHECK(length(job_id)=16),
    target_date TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','captured','researching','completed','partial','unreconstructable')),
    discovered_count INTEGER NOT NULL CHECK(discovered_count >= 0),
    captured_count INTEGER NOT NULL CHECK(captured_count >= 0),
    failed_count INTEGER NOT NULL CHECK(failed_count >= 0),
    authorization_id BLOB(16) NULL CHECK(authorization_id IS NULL OR length(authorization_id)=16),
    research_job_id BLOB(16) NULL CHECK(research_job_id IS NULL OR length(research_job_id)=16),
    research_result_id BLOB(16) NULL CHECK(research_result_id IS NULL OR length(research_result_id)=16),
    digest_id BLOB(16) NULL CHECK(digest_id IS NULL OR length(digest_id)=16),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    completed_at_us INTEGER NULL,
    UNIQUE(profile_id, target_date),
    FOREIGN KEY(profile_id) REFERENCES news_profiles(profile_id),
    FOREIGN KEY(job_id) REFERENCES jobs(job_id),
    FOREIGN KEY(authorization_id) REFERENCES external_access_authorizations(authorization_id),
    FOREIGN KEY(research_job_id) REFERENCES jobs(job_id),
    FOREIGN KEY(research_result_id) REFERENCES research_results(result_id)
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS uq_news_daily_job_identity
    ON jobs(job_type, json_extract(requested_scope_json, '$.profile_id'), json_extract(requested_scope_json, '$.target_date'))
    WHERE job_type = 'news.daily';
CREATE UNIQUE INDEX IF NOT EXISTS uq_news_period_job_identity
    ON jobs(job_type, json_extract(requested_scope_json, '$.profile_id'), json_extract(requested_scope_json, '$.period_kind'), json_extract(requested_scope_json, '$.period_start'))
    WHERE job_type = 'news.period';

CREATE TABLE IF NOT EXISTS news_period_runs (
    period_id BLOB(16) PRIMARY KEY CHECK(length(period_id)=16),
    profile_id BLOB(16) NOT NULL CHECK(length(profile_id)=16),
    job_id BLOB(16) NOT NULL UNIQUE CHECK(length(job_id)=16),
    period_kind TEXT NOT NULL CHECK(period_kind IN ('weekly','monthly')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued','researching','completed','partial','unreconstructable')),
    research_job_id BLOB(16) NULL CHECK(research_job_id IS NULL OR length(research_job_id)=16),
    research_result_id BLOB(16) NULL CHECK(research_result_id IS NULL OR length(research_result_id)=16),
    digest_id BLOB(16) NULL CHECK(digest_id IS NULL OR length(digest_id)=16),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    completed_at_us INTEGER NULL,
    UNIQUE(profile_id, period_kind, period_start),
    FOREIGN KEY(profile_id) REFERENCES news_profiles(profile_id),
    FOREIGN KEY(job_id) REFERENCES jobs(job_id),
    FOREIGN KEY(research_job_id) REFERENCES jobs(job_id),
    FOREIGN KEY(research_result_id) REFERENCES research_results(result_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_discoveries (
    discovery_id BLOB(16) PRIMARY KEY CHECK(length(discovery_id)=16),
    run_id BLOB(16) NOT NULL CHECK(length(run_id)=16),
    news_source_id BLOB(16) NOT NULL CHECK(length(news_source_id)=16),
    canonical_url TEXT NOT NULL,
    url_hash BLOB(32) NOT NULL CHECK(length(url_hash)=32),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    published_at_us INTEGER NULL,
    category_keys_json TEXT NOT NULL CHECK(json_valid(category_keys_json)),
    state TEXT NOT NULL CHECK(state IN ('discovered','captured','failed')),
    article_source_id BLOB(16) NULL CHECK(article_source_id IS NULL OR length(article_source_id)=16),
    failure_reason TEXT NULL,
    discovered_at_us INTEGER NOT NULL,
    UNIQUE(run_id, url_hash),
    FOREIGN KEY(run_id) REFERENCES news_runs(run_id),
    FOREIGN KEY(news_source_id) REFERENCES news_sources(news_source_id),
    FOREIGN KEY(article_source_id) REFERENCES sources(source_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_news_discoveries_source ON news_discoveries(article_source_id) WHERE article_source_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS news_source_run_failures (
    failure_id BLOB(16) PRIMARY KEY CHECK(length(failure_id)=16),
    run_id BLOB(16) NOT NULL CHECK(length(run_id)=16),
    news_source_id BLOB(16) NOT NULL CHECK(length(news_source_id)=16),
    detail TEXT NOT NULL,
    created_at_us INTEGER NOT NULL,
    FOREIGN KEY(run_id) REFERENCES news_runs(run_id),
    FOREIGN KEY(news_source_id) REFERENCES news_sources(news_source_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_events (
    event_id BLOB(16) PRIMARY KEY CHECK(length(event_id)=16),
    run_id BLOB(16) NOT NULL CHECK(length(run_id)=16),
    event_ordinal INTEGER NOT NULL CHECK(event_ordinal >= 0),
    cluster_key BLOB(32) NOT NULL CHECK(length(cluster_key)=32),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    categories_json TEXT NOT NULL CHECK(json_valid(categories_json)),
    source_ids_json TEXT NOT NULL CHECK(json_valid(source_ids_json)),
    contradictions_json TEXT NOT NULL CHECK(json_valid(contradictions_json)),
    created_at_us INTEGER NOT NULL,
    UNIQUE(run_id, event_ordinal),
    UNIQUE(run_id, cluster_key),
    FOREIGN KEY(run_id) REFERENCES news_runs(run_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_event_links (
    from_event_id BLOB(16) NOT NULL CHECK(length(from_event_id)=16),
    to_event_id BLOB(16) NOT NULL CHECK(length(to_event_id)=16),
    relation TEXT NOT NULL CHECK(relation IN ('possible_continuation','related_to')),
    score REAL NOT NULL CHECK(score BETWEEN 0.0 AND 1.0),
    created_at_us INTEGER NOT NULL,
    PRIMARY KEY(from_event_id, to_event_id, relation),
    FOREIGN KEY(from_event_id) REFERENCES news_events(event_id),
    FOREIGN KEY(to_event_id) REFERENCES news_events(event_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS news_digests (
    digest_id BLOB(16) PRIMARY KEY CHECK(length(digest_id)=16),
    profile_id BLOB(16) NOT NULL CHECK(length(profile_id)=16),
    period_kind TEXT NOT NULL CHECK(period_kind IN ('daily','weekly','monthly')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    revision_no INTEGER NOT NULL CHECK(revision_no >= 1),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    research_result_ids_json TEXT NOT NULL CHECK(json_valid(research_result_ids_json)),
    created_at_us INTEGER NOT NULL,
    UNIQUE(profile_id, period_kind, period_start, revision_no),
    FOREIGN KEY(profile_id) REFERENCES news_profiles(profile_id)
) WITHOUT ROWID;
"""
