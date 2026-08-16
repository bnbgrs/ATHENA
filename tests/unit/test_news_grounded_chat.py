from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from athena.chat.generation import ChatGenerationService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.retrieval.news_events import (
    NewsEventContextBuilderService,
    NewsEventSearchService,
)


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(
        self,
    ) -> None:
        self.stream_calls = 0
        self.requests: list[
            tuple[
                ModelChatMessage,
                ...
            ]
        ] = []

    def discover_models(
        self,
    ) -> tuple[
        ModelInfo,
        ...
    ]:
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="primary",
                display_name="primary",
                model_type="llm",
                context_capacity=32768,
                loaded_context_length=4096,
                quantization="Q4_K_M",
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
            ),
        )

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[
            ModelChatMessage
        ],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> Iterator[str]:
        assert model_id == "primary"
        assert max_output_tokens == 800
        assert reasoning_mode == "off"

        self.stream_calls += 1

        self.requests.append(
            tuple(
                messages
            )
        )

        yield (
            "ATHENA News reports launch code 5931 "
            "[NEWS:CTX-001]."
        )


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        allow_nan=False,
    )


def _insert_news_event(
    app: AthenaApplication,
):
    target_date = "2026-08-16"
    summary = (
        "Project Helios announced launch code 5931."
    )

    news_job_id = app.news.queue_date(
        target_date
    )

    run = app.database.connection.execute(
        """
        SELECT *
        FROM news_runs
        WHERE job_id = ?
        """,
        (
            uuid_to_blob(
                news_job_id
            ),
        ),
    ).fetchone()

    assert run is not None

    research_job = app.research.enqueue_local(
        query="News Research for Project Helios"
    )

    scope = app.research.initialize(
        research_job.job_id
    )

    result_id = new_uuid7()
    event_id = new_uuid7()
    now = utc_now_us()

    payload = {
        "summary": summary,
        "findings": [
            summary,
        ],
        "contradictions": [],
        "uncertainty": "",
        "coverage": {
            "candidate_total": 1,
            "processed_count": 1,
            "successful_count": 1,
            "irrelevant_count": 0,
            "failed_count": 0,
            "unavailable_count": 0,
            "excluded_count": 0,
            "eligible_count": 1,
            "coverage_ratio": 1.0,
        },
        "problem_sources": [],
        "snapshot_commit_seq": (
            scope.snapshot_commit_seq
        ),
    }

    content_json = _canonical_json(
        payload
    )

    content_hash = hashlib.sha256(
        content_json.encode(
            "utf-8"
        )
    ).digest()

    finding_hash = hashlib.sha256(
        summary.encode(
            "utf-8"
        )
    ).digest()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE research_scopes
            SET state = 'completed',
                updated_at_us = ?
            WHERE scope_id = ?
            """,
            (
                now,
                uuid_to_blob(
                    scope.scope_id
                ),
            ),
        )

        connection.execute(
            """
            INSERT INTO research_results (
                result_id,
                scope_id,
                final_artifact_id,
                content_json,
                content_hash,
                snapshot_commit_seq,
                model_signature_id,
                synthesis_pipeline_version,
                candidate_total,
                processed_count,
                successful_count,
                irrelevant_count,
                failed_count,
                unavailable_count,
                excluded_count,
                coverage_ratio,
                problem_sources_json,
                created_at_us
            ) VALUES (
                ?, ?, NULL, ?, ?, ?, NULL, ?,
                1, 1, 1, 0, 0, 0, 0,
                1.0, '[]', ?
            )
            """,
            (
                uuid_to_blob(
                    result_id
                ),
                uuid_to_blob(
                    scope.scope_id
                ),
                content_json,
                content_hash,
                scope.snapshot_commit_seq,
                "news-grounded-chat-test-v1",
                now,
            ),
        )

        connection.execute(
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
                ?, ?, 0, ?, 'event',
                'current_development',
                ?, NULL, 'day',
                'Berlin', ?, ?,
                ?, ?, ?, ?, NULL, ?
            )
            """,
            (
                run["run_id"],
                uuid_to_blob(
                    result_id
                ),
                finding_hash,
                target_date,
                _canonical_json(
                    [
                        "Project Helios",
                    ]
                ),
                "announced launch code 5931",
                now,
                now,
                now,
                now,
                now,
            ),
        )

        connection.execute(
            """
            INSERT INTO news_events (
                event_id,
                run_id,
                event_ordinal,
                finding_ordinal,
                cluster_key,
                title,
                summary,
                categories_json,
                source_ids_json,
                contradictions_json,
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
                first_seen_us,
                last_updated_us,
                importance,
                relevance,
                novelty,
                source_count,
                independent_source_count,
                conflicting_source_count,
                research_job_id,
                research_result_id,
                created_at_us
            ) VALUES (
                ?, ?, 0, 0, ?, ?, ?,
                '["technology"]', '[]', '[]',
                ?, NULL, 'day', 'Berlin',
                ?, ?, ?, ?, ?, ?, NULL,
                ?, ?, 0.95, 0.90, 0.85,
                0, 0, 0, ?, ?, ?
            )
            """,
            (
                uuid_to_blob(
                    event_id
                ),
                run["run_id"],
                hashlib.sha256(
                    summary.casefold().encode(
                        "utf-8"
                    )
                ).digest(),
                "Project Helios update",
                summary,
                target_date,
                _canonical_json(
                    [
                        "Project Helios",
                    ]
                ),
                "announced launch code 5931",
                now,
                now,
                now,
                now,
                now,
                now,
                uuid_to_blob(
                    research_job.job_id
                ),
                uuid_to_blob(
                    result_id
                ),
                now,
            ),
        )

        connection.execute(
            """
            UPDATE news_runs
            SET state = 'completed',
                research_job_id = ?,
                research_result_id = ?,
                completed_at_us = ?,
                updated_at_us = ?
            WHERE run_id = ?
            """,
            (
                uuid_to_blob(
                    research_job.job_id
                ),
                uuid_to_blob(
                    result_id
                ),
                now,
                now,
                run["run_id"],
            ),
        )

    return (
        event_id,
        uuid_from_blob(
            bytes(
                run["run_id"]
            )
        ),
        result_id,
        finding_hash,
    )



def test_news_grounded_chat_uses_typed_news_evidence_and_clean_history(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )

    app.start()

    try:
        (
            event_id,
            run_id,
            result_id,
            finding_hash,
        ) = _insert_news_event(
            app
        )

        provider = FakeProvider()

        retrieval = NewsEventSearchService(
            app.database
        )

        builder = NewsEventContextBuilderService(
            retrieval
        )

        service = app.news_grounded_chat

        service.chat_generation = ChatGenerationService(
            app.chat,
            provider,
        )

        service.retrieval = retrieval
        service.context_builder = builder

        chat_id = app.chat.create_chat()

        app.chat.add_user_message(
            chat_id=chat_id,
            content="Earlier question",
        )

        old_assistant = app.chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "old News answer "
                "[NEWS:CTX-777].\n\n"
                "ATHENA_PROVENANCE "
                '{"athena_provenance_version":3,'
                '"evidence":[]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        result = service.send_message(
            chat_id=chat_id,
            content=(
                "What are the latest News "
                "about Project Helios?"
            ),
            requested_model_id="primary",
            max_context_tokens=900,
            max_context_items=4,
            max_recent_conversation_turns=1,
            output_reserve=800,
            safety_margin=100,
            allow_model_prior=False,
        )

        assert provider.stream_calls == 1

        sent = provider.requests[0]

        assert (
            sent[-1].role
            == "user"
        )

        assert (
            sent[-1].content
            == (
                "What are the latest News "
                "about Project Helios?"
            )
        )

        assert any(
            item.role == "user"
            and item.content == "Earlier question"
            for item in sent
        )

        assert all(
            item.role != "assistant"
            for item in sent
        )

        assert all(
            "[NEWS:CTX-777]"
            not in item.content
            for item in sent
        )

        system = sent[0].content

        assert (
            '"evidence_class": "news"'
            in system
        )

        assert (
            str(
                event_id
            )
            in system
        )

        report = (
            result.generation
            .grounding_report
        )

        assert report is not None

        assert (
            report.news_context_ids
            == ("CTX-001",)
        )
        assert (
            report.canonical_context_ids
            == ()
        )
        assert (
            report.research_context_ids
            == ()
        )
        assert (
            report.source_context_ids
            == ()
        )

        persisted = (
            result.generation
            .assistant_message
            .content
        )

        assert persisted is not None
        assert "[NEWS:CTX-001]" in persisted
        assert '"evidence_class":"news"' in persisted

        assert (
            '"news_event_id":"'
            + str(
                event_id
            )
            + '"'
            in persisted
        )

        assert (
            '"news_run_id":"'
            + str(
                run_id
            )
            + '"'
            in persisted
        )

        assert (
            '"research_result_id":"'
            + str(
                result_id
            )
            + '"'
            in persisted
        )

        assert (
            '"finding_sha256":"'
            + finding_hash.hex()
            + '"'
            in persisted
        )

        assert old_assistant.content is not None

        archived = app.chat.load_chat(
            chat_id
        ).messages

        assert any(
            item.message_id
            == old_assistant.message_id
            and item.content
            == old_assistant.content
            for item in archived
        )

        assert (
            "[NEWS:CTX-777]"
            in old_assistant.content
        )

        assert (
            result.processing_run.run_type
            == "chat.news_context_package"
        )

        assert (
            result.processing_run.status
            == "succeeded"
        )

        snapshot = json.loads(
            result.processing_run
            .input_snapshot_json
        )

        refs = snapshot[
            "included_refs"
        ]

        assert any(
            item["entity_type"]
            == "news_event"
            and item["entity_id"]
            == str(
                event_id
            )
            and item["revision_id"]
            is None
            for item in refs
        )

    finally:
        app.stop()
