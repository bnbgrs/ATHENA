from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from athena.chat.generation import ChatGenerationService
from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.retrieval.prior_research import (
    PriorResearchContextBuilderService,
    PriorResearchSearchService,
)


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self) -> None:
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
            "Prior research found code 2468 "
            "[RESEARCH:CTX-001]."
        )


def _insert_completed_result(
    app: AthenaApplication,
):
    job = app.research.enqueue_local(
        query=(
            "Investigate Project Helios "
            "launch code"
        )
    )

    scope = app.research.initialize(
        job.job_id
    )

    now_us = utc_now_us()

    payload = {
        "summary": (
            "Project Helios launch "
            "code is 2468."
        ),
        "findings": [
            "Project Helios uses "
            "code 2468."
        ],
        "contradictions": [],
        "uncertainty": "",
        "coverage": {
            "candidate_total": 0,
            "processed_count": 0,
            "successful_count": 0,
            "irrelevant_count": 0,
            "failed_count": 0,
            "unavailable_count": 0,
            "excluded_count": 0,
            "eligible_count": 0,
            "coverage_ratio": 0.0,
        },
        "problem_sources": [],
        "snapshot_commit_seq": scope.snapshot_commit_seq,
    }

    content_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    content_hash = hashlib.sha256(
        content_json.encode(
            "utf-8"
        )
    ).digest()

    result_id = new_uuid7()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE research_scopes
            SET state = 'completed',
                updated_at_us = ?
            WHERE scope_id = ?
            """,
            (
                now_us,
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
                0, 0, 0, 0, 0, 0, 0,
                0.0, '[]', ?
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
                "test-prior-research-v1",
                now_us,
            ),
        )

    return (
        result_id,
        scope,
        content_hash,
    )


def test_research_grounded_chat_uses_typed_research_evidence_and_clean_history(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )

    for directory in app.paths.required_local_directories:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    app.database.start()

    try:
        (
            result_id,
            scope,
            content_hash,
        ) = _insert_completed_result(
            app
        )

        provider = FakeProvider()

        retrieval = PriorResearchSearchService(
            app.database
        )

        builder = PriorResearchContextBuilderService(
            retrieval
        )

        service = app.research_grounded_chat

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
                "old research answer "
                "[RESEARCH:CTX-777].\n\n"
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
                "What did our previous "
                "research find about "
                "Project Helios?"
            ),
            requested_model_id="primary",
            max_context_tokens=700,
            max_context_items=4,
            max_recent_conversation_turns=1,
            output_reserve=800,
            safety_margin=100,
            allow_model_prior=False,
        )

        assert provider.stream_calls == 1

        sent = provider.requests[0]

        assert sent[-1].role == "user"

        assert (
            sent[-1].content
            == (
                "What did our previous "
                "research find about "
                "Project Helios?"
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
            "[RESEARCH:CTX-777]"
            not in item.content
            for item in sent
        )

        system = sent[0].content

        assert (
            '"evidence_class": "research"'
            in system
        )

        assert str(result_id) in system

        report = result.generation.grounding_report

        assert report is not None

        assert (
            report.research_context_ids
            == ("CTX-001",)
        )
        assert report.canonical_context_ids == ()
        assert report.source_context_ids == ()

        persisted = (
            result.generation
            .assistant_message
            .content
        )

        assert persisted is not None
        assert "[RESEARCH:CTX-001]" in persisted
        assert '"evidence_class":"research"' in persisted

        assert (
            '"research_scope_id":"'
            + str(
                scope.scope_id
            )
            + '"'
            in persisted
        )

        assert (
            '"content_sha256":"'
            + content_hash.hex()
            + '"'
            in persisted
        )

        assert old_assistant.content is not None

        archived = app.chat.load_chat(
            chat_id
        ).messages

        assert any(
            item.message_id == old_assistant.message_id
            and item.content == old_assistant.content
            for item in archived
        )

        assert "[RESEARCH:CTX-777]" in old_assistant.content

        assert (
            result.processing_run.run_type
            == "chat.research_context_package"
        )
        assert result.processing_run.status == "succeeded"

        snapshot = json.loads(
            result.processing_run.input_snapshot_json
        )

        refs = snapshot[
            "included_refs"
        ]

        assert any(
            item["entity_type"] == "research_result"
            and item["entity_id"] == str(result_id)
            and item["revision_id"] is None
            for item in refs
        )

    finally:
        app.database.stop()
