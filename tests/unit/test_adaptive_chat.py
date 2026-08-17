from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from athena.chat.adaptive import (
    AdaptiveChatService,
    AdaptivePlanReason,
    AdaptiveRetrievalMode,
    AdaptiveRetrievalPlan,
    AdaptiveRetrievalPlanner,
)
from athena.chat.models import ChatMessage, ChatThread, MessageType
from athena.retrieval.archive import ArchiveSearchError
from athena.retrieval.news_events import NewsEventSearchError
from athena.retrieval.prior_research import PriorResearchSearchError
from athena.retrieval.search import SearchEntityType


class FakeLocalSearch:
    def __init__(
        self,
        *,
        knowledge_texts: tuple[str, ...] = (),
        claim_texts: tuple[str, ...] = (),
    ) -> None:
        self.knowledge_texts = knowledge_texts
        self.claim_texts = claim_texts
        self.calls: list[
            tuple[
                str,
                int,
                SearchEntityType | None,
            ]
        ] = []

    def search(
        self,
        query: str,
        *,
        limit: int,
        entity_type: SearchEntityType | None = None,
    ):
        self.calls.append(
            (
                query,
                limit,
                entity_type,
            )
        )

        if entity_type is SearchEntityType.KNOWLEDGE:
            values = self.knowledge_texts
        elif entity_type is SearchEntityType.CLAIM:
            values = self.claim_texts
        else:
            raise AssertionError(
                "Adaptive planner must use typed canonical probes."
            )

        return tuple(
            SimpleNamespace(
                title=None,
                text=text,
            )
            for text in values[:limit]
        )


class FakeArchiveSearch:
    def __init__(
        self,
        *,
        texts: tuple[str, ...] = (),
        fail: bool = False,
    ) -> None:
        self.texts = texts
        self.fail = fail
        self.calls: list[
            tuple[str, int]
        ] = []

    def search(
        self,
        query: str,
        *,
        limit: int,
    ):
        self.calls.append(
            (
                query,
                limit,
            )
        )

        if self.fail:
            raise ArchiveSearchError(
                "synthetic archive probe failure"
            )

        return tuple(
            SimpleNamespace(
                source_name=None,
                text=text,
            )
            for text in self.texts[:limit]
        )


class FakeNewsEventSearch:
    def __init__(
        self,
        *,
        texts: tuple[str, ...] = (),
        fail: bool = False,
    ) -> None:
        self.texts = texts
        self.fail = fail
        self.calls: list[
            tuple[str, int]
        ] = []

    def search(
        self,
        query: str,
        *,
        limit: int,
    ):
        self.calls.append(
            (
                query,
                limit,
            )
        )

        if self.fail:
            raise NewsEventSearchError(
                "synthetic News probe failure"
            )

        return tuple(
            SimpleNamespace(
                text=text,
            )
            for text in self.texts[:limit]
        )


class FakePriorResearchSearch:
    def __init__(
        self,
        *,
        texts: tuple[str, ...] = (),
        fail: bool = False,
    ) -> None:
        self.texts = texts
        self.fail = fail
        self.calls: list[
            tuple[str, int]
        ] = []

    def search(
        self,
        query: str,
        *,
        limit: int,
    ):
        self.calls.append(
            (
                query,
                limit,
            )
        )

        if self.fail:
            raise PriorResearchSearchError(
                "synthetic research probe failure"
            )

        return tuple(
            SimpleNamespace(
                text=text,
            )
            for text in self.texts[:limit]
        )


def planner(
    *,
    knowledge_texts: tuple[str, ...] = (),
    claim_texts: tuple[str, ...] = (),
    archive_texts: tuple[str, ...] = (),
    archive_fail: bool = False,
    research_texts: tuple[str, ...] = (),
    research_fail: bool = False,
    news_texts: tuple[str, ...] = (),
    news_fail: bool = False,
):
    local = FakeLocalSearch(
        knowledge_texts=knowledge_texts,
        claim_texts=claim_texts,
    )

    archive = FakeArchiveSearch(
        texts=archive_texts,
        fail=archive_fail,
    )

    research = FakePriorResearchSearch(
        texts=research_texts,
        fail=research_fail,
    )

    news = FakeNewsEventSearch(
        texts=news_texts,
        fail=news_fail,
    )

    planned = AdaptiveRetrievalPlanner(
        local_search=local,  # type: ignore[arg-type]
        archive_search=archive,  # type: ignore[arg-type]
        prior_research=research,  # type: ignore[arg-type]
        news_events=news,  # type: ignore[arg-type]
    )

    return planned, local, archive


def test_explicit_memory_and_source_selects_unified_without_probes() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Was wei\u00dft du noch \u00fcber Berlin und "
        "was steht im importierten PDF dazu?"
    )

    assert result.mode is AdaptiveRetrievalMode.UNIFIED
    assert (
        result.reason
        is AdaptivePlanReason.EXPLICIT_MEMORY_AND_SOURCE
    )
    assert result.probe_query is None
    assert local.calls == []
    assert archive.calls == []


def test_explicit_source_selects_source_without_probes() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Was steht im PDF \u00fcber Berlin?"
    )

    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert result.reason is AdaptivePlanReason.EXPLICIT_SOURCE
    assert local.calls == []
    assert archive.calls == []


def test_only_wissen_noch_is_explicit_memory() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Was wei\u00dft du noch \u00fcber Berlin?"
    )

    assert result.mode is AdaptiveRetrievalMode.MEMORY
    assert result.reason is AdaptivePlanReason.EXPLICIT_MEMORY
    assert local.calls == []
    assert archive.calls == []


def test_generic_wissen_ueber_is_not_forced_to_memory() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Was wei\u00dft du \u00fcber Berlin?"
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT
    )
    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_canonical_knowledge_hit_stops_before_archive() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "Berlin ist die Hauptstadt von Deutschland.",
        ),
        archive_texts=(
            "Deutschland hat Berlin als Hauptstadt.",
        ),
    )

    result = planned.plan(
        "Welche Hauptstadt hat Deutschland?"
    )

    assert result.mode is AdaptiveRetrievalMode.MEMORY
    assert (
        result.reason
        is AdaptivePlanReason.CANONICAL_LEXICAL_HIT
    )
    assert result.canonical_probe_hit is True
    assert result.archive_probe_hit is False

    assert len(local.calls) == 1
    assert local.calls[0][1] == 5
    assert (
        local.calls[0][2]
        is SearchEntityType.KNOWLEDGE
    )

    assert archive.calls == []


def test_claim_probe_runs_only_after_knowledge_miss() -> None:
    planned, local, archive = planner(
        claim_texts=(
            "Berlin ist die Hauptstadt von Deutschland.",
        ),
        archive_texts=(
            "Berlin Hauptstadt Deutschland",
        ),
    )

    result = planned.plan(
        "Welche Hauptstadt hat Deutschland?"
    )

    assert result.mode is AdaptiveRetrievalMode.MEMORY

    assert [
        call[2]
        for call in local.calls
    ] == [
        SearchEntityType.KNOWLEDGE,
        SearchEntityType.CLAIM,
    ]

    assert archive.calls == []


def test_one_of_multiple_terms_is_not_enough_for_canonical_route() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "Orion ist ein interner Codename.",
        ),
        archive_texts=(
            "Projekt Orion verwendet die Kennzahl 42.",
        ),
    )

    result = planned.plan(
        "Welche Kennzahl enth\u00e4lt Projekt Orion?"
    )

    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert result.canonical_probe_hit is False
    assert result.archive_probe_hit is True

    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_archive_probe_runs_after_canonical_miss() -> None:
    planned, local, archive = planner(
        archive_texts=(
            "Projekt Orion Kennzahl 42",
        ),
    )

    result = planned.plan(
        "Welche Kennzahl enth\u00e4lt Projekt Orion?"
    )

    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert (
        result.reason
        is AdaptivePlanReason.ARCHIVE_LEXICAL_HIT
    )

    assert [
        call[2]
        for call in local.calls
    ] == [
        SearchEntityType.KNOWLEDGE,
        SearchEntityType.CLAIM,
    ]

    assert len(archive.calls) == 1


def test_natural_local_data_question_routes_to_archive_without_noise_inflation() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "ATHENA ist ein lokales Wissenssystem.",
        ),
        archive_texts=(
            "Der Ladezustand des Projekts "
            "ATHENA-LIVE-F8164C762FE3 betr\u00e4gt 83 Prozent. "
            "Die technische Leiterin ist Mira-F8164C762FE3.",
        ),
    )

    result = planned.plan(
        "Was ist laut meinen vorhandenen lokalen Daten "
        "der Ladezustand des Projekts ATHENA-LIVE-F8164C762FE3, "
        "und wer ist die technische Leiterin?"
    )

    assert (
        result.probe_query
        == "ladezustand athena live f8164c762fe3 technische leiterin"
    )
    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert (
        result.reason
        is AdaptivePlanReason.ARCHIVE_LEXICAL_HIT
    )
    assert result.canonical_probe_hit is False
    assert result.archive_probe_hit is True

    # A weak higher-priority ATHENA-only canonical hit must not shadow
    # the strongly matching Source.
    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_vague_local_data_language_does_not_select_arbitrary_domain() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "Unrelated canonical information.",
        ),
        archive_texts=(
            "Unrelated archived information.",
        ),
    )

    result = planned.plan(
        "Was ist laut meinen vorhandenen lokalen Daten?"
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_INFORMATIVE_QUERY_TERMS
    )
    assert result.probe_query is None
    assert local.calls == []
    assert archive.calls == []


def test_distinctive_identifier_can_support_strong_partial_long_probe() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "ATHENA ist ein lokales Wissenssystem.",
        ),
        archive_texts=(
            "ATHENA-LIVE-F8164C762FE3 "
            "Ladezustand technische Leiterin",
        ),
    )

    result = planned.plan(
        "Pr\u00fcfe Historie Risiken Abh\u00e4ngigkeiten "
        "Ladezustand ATHENA-LIVE-F8164C762FE3 "
        "technische Leiterin."
    )

    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert result.canonical_probe_hit is False
    assert result.archive_probe_hit is True
    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_identifier_alone_cannot_rescue_unrelated_long_probe() -> None:
    planned, local, archive = planner(
        archive_texts=(
            "Interne Referenz F8164C762FE3.",
        ),
    )

    result = planned.plan(
        "Vergleiche Architektur Sicherheit Performance Skalierung "
        "Wartbarkeit Kosten Betrieb Dokumentation Governance "
        "Datenschutz Netzwerk Speicher Datenbank "
        "ATHENA-LIVE-F8164C762FE3."
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT
    )
    assert result.probe_query is not None
    assert "f8164c762fe3" in result.probe_query
    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_creative_task_does_not_force_direct_but_weak_hit_is_rejected() -> None:
    planned, local, archive = planner(
        knowledge_texts=(
            "Berlin ist eine Stadt in Deutschland.",
        ),
    )

    result = planned.plan(
        "Schreibe ein Gedicht \u00fcber Berlin."
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT
    )

    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_local_knowledge_can_support_a_transformation_task() -> None:
    planned, _local, archive = planner(
        knowledge_texts=(
            "ATHENA ist unser lokales Wissenssystem.",
        ),
    )

    result = planned.plan(
        "Fasse unser Wissen \u00fcber ATHENA zusammen."
    )

    assert result.mode is AdaptiveRetrievalMode.MEMORY
    assert (
        result.reason
        is AdaptivePlanReason.CANONICAL_LEXICAL_HIT
    )
    assert archive.calls == []


def test_single_distinctive_term_can_route_to_canonical() -> None:
    planned, _local, archive = planner(
        knowledge_texts=(
            "ATHENA ist unser lokales Wissenssystem.",
        ),
    )

    result = planned.plan(
        "Erkl\u00e4re ATHENA."
    )

    assert result.mode is AdaptiveRetrievalMode.MEMORY
    assert result.probe_query == "athena"
    assert archive.calls == []


def test_no_local_lexical_hit_falls_back_to_direct() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Warum leuchten Sterne?"
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT
    )

    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_archive_probe_failure_is_transparent() -> None:
    planned, _local, _archive = planner(
        archive_fail=True,
    )

    result = planned.plan(
        "Warum leuchten Sterne?"
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith(
        "archive_probe_unavailable:"
    )


def test_stopword_only_followup_does_not_probe_without_contextualization_yet() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Und wie?"
    )

    assert result.mode is AdaptiveRetrievalMode.DIRECT
    assert (
        result.reason
        is AdaptivePlanReason.NO_INFORMATIVE_QUERY_TERMS
    )

    assert local.calls == []
    assert archive.calls == []


class FakeChatHistory:
    def __init__(
        self,
        messages: tuple[ChatMessage, ...] = (),
    ) -> None:
        self.messages = messages

    def load_chat(
        self,
        chat_id: uuid.UUID,
    ) -> ChatThread:
        return ChatThread(
            chat_id=chat_id,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=self.messages,
        )


def _chat_message(
    *,
    chat_id: uuid.UUID,
    sequence_no: int,
    message_type: MessageType,
    content: str,
) -> ChatMessage:
    return ChatMessage(
        message_id=uuid.uuid4(),
        chat_id=chat_id,
        sequence_no=sequence_no,
        message_type=message_type,
        actor_id=(
            uuid.uuid4()
            if message_type is MessageType.USER
            else None
        ),
        created_at_us=sequence_no,
        revision_id=uuid.uuid4(),
        content=content,
        content_format="text/plain",
    )


class StubPlanner:
    def __init__(
        self,
        mode: AdaptiveRetrievalMode,
    ) -> None:
        self.mode = mode
        self.calls: list[str] = []

    def plan(
        self,
        content: str,
    ) -> AdaptiveRetrievalPlan:
        self.calls.append(content)

        return AdaptiveRetrievalPlan(
            mode=self.mode,
            reason=AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT,
            probe_query="probe",
            canonical_probe_hit=False,
            archive_probe_hit=False,
            warnings=(),
        )


class FakeDelegate:
    def __init__(self) -> None:
        self.calls: list[
            dict[str, object]
        ] = []

    def send_message(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)

        return SimpleNamespace(
            generation=SimpleNamespace(
                marker=uuid.uuid4(),
            )
        )



def _adaptive_runtime(
    *,
    planned: AdaptiveRetrievalPlanner,
    chat: FakeChatHistory,
):
    direct = FakeDelegate()
    memory = FakeDelegate()
    source = FakeDelegate()
    unified = FakeDelegate()
    research = FakeDelegate()
    news = FakeDelegate()

    service = AdaptiveChatService(
        chat=chat,  # type: ignore[arg-type]
        planner=planned,
        direct_chat=direct,  # type: ignore[arg-type]
        memory_chat=memory,  # type: ignore[arg-type]
        source_grounded_chat=source,  # type: ignore[arg-type]
        unified_local_chat=unified,  # type: ignore[arg-type]
        research_grounded_chat=research,  # type: ignore[arg-type]
        news_grounded_chat=news,  # type: ignore[arg-type]
    )

    return (
        service,
        direct,
        memory,
        source,
        unified,
    )


def test_followup_contextualizes_retrieval_but_preserves_current_user_content() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="Welche Hauptstadt hat Deutschland?",
    )

    planned, local, archive = planner(
        knowledge_texts=(
            "Berlin ist die Hauptstadt von Deutschland.",
        ),
    )

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory((anchor,)),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Und warum?",
    )

    expected_query = (
        "Welche Hauptstadt hat Deutschland?\n"
        "Und warum?"
    )

    assert result.contextualized is True
    assert (
        result.context_anchor_message_id
        == anchor.message_id
    )
    assert result.retrieval_query == expected_query
    assert result.plan.mode is AdaptiveRetrievalMode.MEMORY

    assert direct.calls == []
    assert source.calls == []
    assert unified.calls == []

    assert len(memory.calls) == 1
    assert (
        memory.calls[0]["content"]
        == "Und warum?"
    )
    assert (
        memory.calls[0]["retrieval_query"]
        == expected_query
    )

    assert len(local.calls) == 1
    assert archive.calls == []


def test_followup_inherits_explicit_source_domain_without_reprobing() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="Was steht im importierten PDF \u00fcber Berlin?",
    )

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory((anchor,)),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Und warum?",
    )

    assert result.contextualized is True
    assert result.plan.mode is AdaptiveRetrievalMode.SOURCES
    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    assert direct.calls == []
    assert memory.calls == []
    assert unified.calls == []
    assert len(source.calls) == 1

    assert local.calls == []
    assert archive.calls == []


def test_current_explicit_source_followup_overrides_memory_anchor() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="Was wei\u00dft du noch \u00fcber Berlin?",
    )

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory((anchor,)),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Was sagen die Quellen dazu?",
    )

    assert result.contextualized is True
    assert result.plan.mode is AdaptiveRetrievalMode.SOURCES
    assert (
        result.plan.reason
        is AdaptivePlanReason.EXPLICIT_SOURCE
    )

    assert direct.calls == []
    assert memory.calls == []
    assert unified.calls == []
    assert len(source.calls) == 1

    assert local.calls == []
    assert archive.calls == []


def test_followup_skips_intermediate_followup_anchor() -> None:
    chat_id = uuid.uuid4()

    substantive = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="Was steht im PDF \u00fcber Berlin?",
    )

    prior_followup = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content="Und warum?",
    )

    planned, _local, _archive = planner()

    (
        service,
        _direct,
        _memory,
        source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                substantive,
                prior_followup,
            )
        ),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Und genauer?",
    )

    assert result.contextualized is True
    assert (
        result.context_anchor_message_id
        == substantive.message_id
    )
    assert result.plan.mode is AdaptiveRetrievalMode.SOURCES
    assert len(source.calls) == 1


def test_non_followup_does_not_reuse_prior_domain() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="Was steht im PDF \u00fcber Berlin?",
    )

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory((anchor,)),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Warum leuchten Sterne?",
    )

    assert result.contextualized is False
    assert result.context_anchor_message_id is None
    assert (
        result.retrieval_query
        == "Warum leuchten Sterne?"
    )
    assert result.plan.mode is AdaptiveRetrievalMode.DIRECT

    assert len(direct.calls) == 1
    assert memory.calls == []
    assert source.calls == []
    assert unified.calls == []

    assert len(local.calls) == 2
    assert len(archive.calls) == 1


def test_followup_without_anchor_remains_uncontextualized() -> None:
    chat_id = uuid.uuid4()

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Und warum?",
    )

    assert result.contextualized is False
    assert result.context_anchor_message_id is None
    assert result.retrieval_query == "Und warum?"
    assert result.plan.mode is AdaptiveRetrievalMode.DIRECT

    assert len(direct.calls) == 1
    assert memory.calls == []
    assert source.calls == []
    assert unified.calls == []

    assert local.calls == []
    assert archive.calls == []



def test_adaptive_canonical_memory_route_requests_canonical_only_evidence() -> None:
    chat_id = uuid.uuid4()

    planned, _local, _archive = planner(
        knowledge_texts=(
            "Athenafalke verwendet die Kennzahl 7319.",
        ),
    )

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Welche Kennzahl verwendet Athenafalke?",
    )

    assert result.plan.mode is AdaptiveRetrievalMode.MEMORY

    assert direct.calls == []
    assert source.calls == []
    assert unified.calls == []

    assert len(memory.calls) == 1

    assert (
        memory.calls[0]["canonical_only_retrieval"]
        is True
    )


def test_adaptive_explicit_conversation_recall_allows_chat_message_evidence() -> None:
    chat_id = uuid.uuid4()

    planned, _local, _archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Was haben wir im Chat besprochen?",
    )

    assert result.plan.mode is AdaptiveRetrievalMode.MEMORY

    assert direct.calls == []
    assert source.calls == []
    assert unified.calls == []

    assert len(memory.calls) == 1

    assert (
        memory.calls[0]["canonical_only_retrieval"]
        is False
    )


def test_adaptive_weisst_du_noch_uses_canonical_memory_not_raw_chat() -> None:
    chat_id = uuid.uuid4()

    planned, _local, _archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Was weisst du noch ueber Athenafalke?",
    )

    assert result.plan.mode is AdaptiveRetrievalMode.MEMORY
    assert len(memory.calls) == 1

    assert (
        memory.calls[0]["canonical_only_retrieval"]
        is True
    )


@pytest.mark.parametrize(
    (
        "mode",
        "expected_delegate",
    ),
    (
        (
            AdaptiveRetrievalMode.DIRECT,
            "direct",
        ),
        (
            AdaptiveRetrievalMode.MEMORY,
            "memory",
        ),
        (
            AdaptiveRetrievalMode.SOURCES,
            "source",
        ),
        (
            AdaptiveRetrievalMode.UNIFIED,
            "unified",
        ),
    ),
)
def test_adaptive_chat_delegates_exactly_once(
    mode: AdaptiveRetrievalMode,
    expected_delegate: str,
) -> None:
    planned = StubPlanner(mode)

    direct = FakeDelegate()
    memory = FakeDelegate()
    source = FakeDelegate()
    unified = FakeDelegate()

    service = AdaptiveChatService(
        chat=FakeChatHistory(),  # type: ignore[arg-type]
        planner=planned,  # type: ignore[arg-type]
        direct_chat=direct,  # type: ignore[arg-type]
        memory_chat=memory,  # type: ignore[arg-type]
        source_grounded_chat=source,  # type: ignore[arg-type]
        unified_local_chat=unified,  # type: ignore[arg-type]
    )

    result = service.send_message(
        chat_id=uuid.uuid4(),
        content="Adaptive test",
        requested_model_id="primary",
        requested_embedding_model_id="embed",
        max_memory_context_tokens=1300,
        max_memory_context_items=7,
        max_memory_items=5,
        max_source_context_tokens=1500,
        max_source_context_items=6,
        effective_context_limit=8192,
        output_reserve=1000,
        safety_margin=100,
        allow_model_prior=False,
    )

    delegates = {
        "direct": direct,
        "memory": memory,
        "source": source,
        "unified": unified,
    }

    assert planned.calls == [
        "Adaptive test"
    ]

    for name, delegate in delegates.items():
        if name == expected_delegate:
            assert len(delegate.calls) == 1
        else:
            assert delegate.calls == []

    assert result.plan.mode is mode

    if mode is AdaptiveRetrievalMode.DIRECT:
        call = direct.calls[0]

        assert (
            "requested_embedding_model_id"
            not in call
        )

        assert (
            "allow_model_prior"
            not in call
        )

    else:
        selected = delegates[
            expected_delegate
        ].calls[0]

        assert (
            selected[
                "requested_embedding_model_id"
            ]
            == "embed"
        )

        assert (
            selected[
                "allow_model_prior"
            ]
            is False
        )



def test_explicit_prior_research_selects_research_without_storage_probes() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "What did our prior research find about Project Helios?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.RESEARCH
    )
    assert (
        result.reason
        is AdaptivePlanReason.EXPLICIT_RESEARCH
    )
    assert result.probe_query is None
    assert local.calls == []
    assert archive.calls == []

    research = planned.prior_research

    assert research is not None
    assert research.calls == []


def test_canonical_hit_still_beats_generic_prior_research_hit() -> None:
    planned, _local, archive = planner(
        knowledge_texts=(
            "Project Helios uses launch code 2468.",
        ),
        research_texts=(
            "Project Helios uses launch code 2468.",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.MEMORY
    )

    research = planned.prior_research

    assert research is not None
    assert research.calls == []
    assert archive.calls == []


def test_prior_research_hit_runs_after_canonical_miss_before_archive() -> None:
    planned, local, archive = planner(
        research_texts=(
            "Project Helios launch code 2468",
        ),
        archive_texts=(
            "Project Helios launch code 9999",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.RESEARCH
    )
    assert (
        result.reason
        is AdaptivePlanReason.RESEARCH_LEXICAL_HIT
    )
    assert result.research_probe_hit is True
    assert len(local.calls) == 2

    research = planned.prior_research

    assert research is not None
    assert len(
        research.calls
    ) == 1

    assert archive.calls == []


def test_prior_research_probe_failure_is_transparent_and_archive_can_win() -> None:
    planned, _local, archive = planner(
        research_fail=True,
        archive_texts=(
            "Project Helios launch code 2468",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.SOURCES
    )
    assert result.archive_probe_hit is True

    assert any(
        warning.startswith(
            "research_probe_unavailable:"
        )
        for warning in result.warnings
    )

    assert len(archive.calls) == 1


def test_followup_inherits_explicit_prior_research_domain() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "What did our prior research find "
            "about Project Helios?"
        ),
    )

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (anchor,)
        ),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="And which code exactly?",
    )

    expected_query = (
        "What did our prior research find "
        "about Project Helios?\n"
        "And which code exactly?"
    )

    assert result.contextualized is True
    assert (
        result.context_anchor_message_id
        == anchor.message_id
    )
    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.RESEARCH
    )
    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )
    assert (
        result.retrieval_query
        == expected_query
    )

    assert direct.calls == []
    assert memory.calls == []
    assert source.calls == []
    assert unified.calls == []

    research = service.research_grounded_chat

    assert research is not None
    assert len(
        research.calls
    ) == 1

    calls = research.calls

    assert (
        calls[0]["content"]
        == "And which code exactly?"
    )

    assert (
        calls[0]["retrieval_query"]
        == expected_query
    )

    assert (
        "requested_embedding_model_id"
        not in calls[0]
    )

    assert local.calls == []
    assert archive.calls == []



def test_explicit_news_selects_news_without_storage_probes() -> None:
    planned, local, archive = planner()

    result = planned.plan(
        "Was sind die neuesten Nachrichten zu Project Helios?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.NEWS
    )
    assert (
        result.reason
        is AdaptivePlanReason.EXPLICIT_NEWS
    )
    assert result.probe_query is None
    assert local.calls == []
    assert archive.calls == []

    research = planned.prior_research
    news = planned.news_events

    assert research is not None
    assert news is not None
    assert research.calls == []
    assert news.calls == []


def test_explicit_source_remains_more_specific_than_news_wording() -> None:
    planned, _local, _archive = planner()

    result = planned.plan(
        "Welche Nachrichten stehen in diesem PDF?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.SOURCES
    )


def test_prior_research_hit_still_beats_generic_news_hit() -> None:
    planned, _local, archive = planner(
        research_texts=(
            "Project Helios launch code 2468",
        ),
        news_texts=(
            "Project Helios launch code 5931",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.RESEARCH
    )

    news = planned.news_events

    assert news is not None
    assert news.calls == []
    assert archive.calls == []


def test_news_hit_runs_after_research_miss_before_archive() -> None:
    planned, local, archive = planner(
        news_texts=(
            "Project Helios launch code 5931",
        ),
        archive_texts=(
            "Project Helios launch code 9999",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.NEWS
    )
    assert (
        result.reason
        is AdaptivePlanReason.NEWS_LEXICAL_HIT
    )
    assert result.news_probe_hit is True
    assert len(local.calls) == 2

    research = planned.prior_research
    news = planned.news_events

    assert research is not None
    assert news is not None
    assert len(
        research.calls
    ) == 1
    assert len(
        news.calls
    ) == 1
    assert archive.calls == []


def test_news_probe_failure_is_transparent_and_archive_can_win() -> None:
    planned, _local, archive = planner(
        news_fail=True,
        archive_texts=(
            "Project Helios launch code 5931",
        ),
    )

    result = planned.plan(
        "Which launch code does Project Helios use?"
    )

    assert (
        result.mode
        is AdaptiveRetrievalMode.SOURCES
    )
    assert result.archive_probe_hit is True

    assert any(
        warning.startswith(
            "news_probe_unavailable:"
        )
        for warning in result.warnings
    )

    assert len(
        archive.calls
    ) == 1


def test_followup_inherits_explicit_news_domain() -> None:
    chat_id = uuid.uuid4()

    anchor = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "Was sind die neuesten Nachrichten "
            "zu Project Helios?"
        ),
    )

    planned, local, archive = planner()

    (
        service,
        direct,
        memory,
        source,
        unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (anchor,)
        ),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="Und welcher Startcode genau?",
    )

    expected_query = (
        "Was sind die neuesten Nachrichten "
        "zu Project Helios?\n"
        "Und welcher Startcode genau?"
    )

    assert result.contextualized is True
    assert (
        result.context_anchor_message_id
        == anchor.message_id
    )
    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.NEWS
    )
    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )
    assert (
        result.retrieval_query
        == expected_query
    )

    assert direct.calls == []
    assert memory.calls == []
    assert source.calls == []
    assert unified.calls == []

    news = service.news_grounded_chat

    assert news is not None

    calls = news.calls

    assert len(
        calls
    ) == 1

    assert (
        calls[0]["content"]
        == "Und welcher Startcode genau?"
    )

    assert (
        calls[0]["retrieval_query"]
        == expected_query
    )

    assert (
        "requested_embedding_model_id"
        not in calls[0]
    )

    assert local.calls == []
    assert archive.calls == []


def test_named_entity_mismatch_does_not_let_canonical_shadow_research() -> None:
    planned, _local, _archive = planner(
        knowledge_texts=(
            "Project Atlas has assigned code 1101.",
        ),
        research_texts=(
            "Project Borealis has assigned code 2202.",
        ),
    )

    result = planned.plan(
        "What code is assigned to Project Borealis?"
    )

    assert result.mode is AdaptiveRetrievalMode.RESEARCH
    assert result.reason is AdaptivePlanReason.RESEARCH_LEXICAL_HIT
    assert result.canonical_probe_hit is False
    assert result.research_probe_hit is True


def test_named_entity_mismatch_does_not_let_research_shadow_news() -> None:
    planned, _local, _archive = planner(
        research_texts=(
            "Project Atlas has assigned code 1101.",
        ),
        news_texts=(
            "Project Borealis has assigned code 2202.",
        ),
    )

    result = planned.plan(
        "What code is assigned to Project Borealis?"
    )

    assert result.mode is AdaptiveRetrievalMode.NEWS
    assert result.reason is AdaptivePlanReason.NEWS_LEXICAL_HIT
    assert result.research_probe_hit is False
    assert result.news_probe_hit is True


def test_named_entity_mismatch_does_not_let_news_shadow_archive() -> None:
    planned, _local, _archive = planner(
        news_texts=(
            "Project Atlas has assigned code 1101.",
        ),
        archive_texts=(
            "Project Borealis has assigned code 2202.",
        ),
    )

    result = planned.plan(
        "What code is assigned to Project Borealis?"
    )

    assert result.mode is AdaptiveRetrievalMode.SOURCES
    assert result.reason is AdaptivePlanReason.ARCHIVE_LEXICAL_HIT
    assert result.news_probe_hit is False
    assert result.archive_probe_hit is True




@pytest.mark.parametrize(
    ("switch_content", "expected_mode"),
    (
        (
            (
                "And according to this document, "
                "what code is assigned to Project Atlas?"
            ),
            AdaptiveRetrievalMode.SOURCES,
        ),
        (
            (
                "And what did our previous research "
                "find about Project Atlas assigned code?"
            ),
            AdaptiveRetrievalMode.RESEARCH,
        ),
        (
            (
                "And remember Project Atlas "
                "and its assigned code."
            ),
            AdaptiveRetrievalMode.MEMORY,
        ),
        (
            (
                "And remember Project Atlas, "
                "and according to this document "
                "what code is assigned?"
            ),
            AdaptiveRetrievalMode.UNIFIED,
        ),
    ),
)
def test_self_contained_explicit_followup_switch_becomes_content_and_domain_anchor(
    switch_content: str,
    expected_mode: AdaptiveRetrievalMode,
) -> None:
    chat_id = uuid.uuid4()

    older_topic = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "What is the latest news "
            "about Project Atlas?"
        ),
    )

    intermediate_followup = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content="And the exact code?",
    )

    explicit_switch = _chat_message(
        chat_id=chat_id,
        sequence_no=3,
        message_type=MessageType.USER,
        content=switch_content,
    )

    planned, local, archive = planner()

    (
        service,
        _direct,
        _memory,
        _source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                older_topic,
                intermediate_followup,
                explicit_switch,
            )
        ),
    )

    current = "And the exact code?"

    result = service.send_message(
        chat_id=chat_id,
        content=current,
    )

    assert result.contextualized is True

    # The explicit switch is self-contained enough to replace the old
    # topic anchor as well as the inherited domain.
    assert (
        result.context_anchor_message_id
        == explicit_switch.message_id
    )

    assert (
        result.retrieval_query
        == explicit_switch.content
        + "\n"
        + current
    )

    assert result.plan.mode is expected_mode

    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    # Route inheritance itself performs no lexical routing probe.
    assert local.calls == []
    assert archive.calls == []


def test_stale_explicit_domain_before_new_substantive_anchor_is_not_inherited() -> None:
    chat_id = uuid.uuid4()

    stale_news = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content="What is the latest news about Project Atlas?",
    )

    newer_substantive = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content="What code is assigned to Project Borealis?",
    )

    planned, _local, _archive = planner(
        research_texts=(
            "Project Borealis is assigned research code 2202.",
        ),
    )

    (
        service,
        _direct,
        _memory,
        _source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                stale_news,
                newer_substantive,
            )
        ),
    )

    result = service.send_message(
        chat_id=chat_id,
        content="And the exact code?",
    )

    assert result.contextualized is True
    assert (
        result.context_anchor_message_id
        == newer_substantive.message_id
    )

    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.RESEARCH
    )

    assert (
        result.plan.reason
        is AdaptivePlanReason.RESEARCH_LEXICAL_HIT
    )

    assert (
        result.plan.reason
        is not AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )


def test_latest_explicit_anaphoric_turn_becomes_content_anchor_fallback() -> None:
    chat_id = uuid.uuid4()

    older_source = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "According to this document, "
            "what code is assigned to Project Atlas?"
        ),
    )

    intermediate_followup = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content="And the exact code?",
    )

    explicit_news = _chat_message(
        chat_id=chat_id,
        sequence_no=3,
        message_type=MessageType.USER,
        content=(
            "And what is the latest news "
            "about Project Atlas?"
        ),
    )

    planned, local, archive = planner()

    (
        service,
        _direct,
        _memory,
        _source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                older_source,
                intermediate_followup,
                explicit_news,
            )
        ),
    )

    current = "And the exact code?"

    result = service.send_message(
        chat_id=chat_id,
        content=current,
    )

    assert result.contextualized is True

    # All three historical turns look anaphoric. The newest explicit
    # routing turn therefore becomes the safe content fallback.
    assert (
        result.context_anchor_message_id
        == explicit_news.message_id
    )

    assert (
        result.retrieval_query
        == explicit_news.content
        + "\n"
        + current
    )

    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.NEWS
    )

    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    assert local.calls == []
    assert archive.calls == []


def test_anaphoric_explicit_source_can_anchor_followup_without_older_topic() -> None:
    chat_id = uuid.uuid4()

    source_turn = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "According to this document, "
            "what code is assigned to Project Atlas?"
        ),
    )

    planned, local, archive = planner()

    (
        service,
        _direct,
        _memory,
        source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                source_turn,
            )
        ),
    )

    current = "And the exact code?"

    result = service.send_message(
        chat_id=chat_id,
        content=current,
    )

    assert result.contextualized is True

    assert (
        result.context_anchor_message_id
        == source_turn.message_id
    )

    assert (
        result.retrieval_query
        == source_turn.content
        + "\n"
        + current
    )

    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.SOURCES
    )

    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    assert len(source.calls) == 1
    assert local.calls == []
    assert archive.calls == []


def test_cross_topic_explicit_source_switch_replaces_old_topic_anchor() -> None:
    chat_id = uuid.uuid4()

    old_news_topic = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "What is the latest news "
            "about Project Atlas?"
        ),
    )

    source_borealis = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content=(
            "And according to this document, "
            "what code is assigned to Project Borealis?"
        ),
    )

    planned, local, archive = planner()

    (
        service,
        _direct,
        _memory,
        source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                old_news_topic,
                source_borealis,
            )
        ),
    )

    current = "And the exact code?"

    result = service.send_message(
        chat_id=chat_id,
        content=current,
    )

    assert result.contextualized is True

    assert (
        result.context_anchor_message_id
        == source_borealis.message_id
    )

    assert (
        result.retrieval_query
        == source_borealis.content
        + "\n"
        + current
    )

    assert (
        "Project Borealis"
        in result.retrieval_query
    )

    assert (
        "Project Atlas"
        not in result.retrieval_query
    )

    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.SOURCES
    )

    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    assert len(source.calls) == 1
    assert local.calls == []
    assert archive.calls == []


def test_weak_explicit_domain_switch_keeps_older_substantive_topic_anchor() -> None:
    chat_id = uuid.uuid4()

    substantive_topic = _chat_message(
        chat_id=chat_id,
        sequence_no=1,
        message_type=MessageType.USER,
        content=(
            "What code is assigned "
            "to Project Borealis?"
        ),
    )

    weak_news_switch = _chat_message(
        chat_id=chat_id,
        sequence_no=2,
        message_type=MessageType.USER,
        content="And what about the news?",
    )

    planned, local, archive = planner()

    (
        service,
        _direct,
        _memory,
        _source,
        _unified,
    ) = _adaptive_runtime(
        planned=planned,
        chat=FakeChatHistory(
            (
                substantive_topic,
                weak_news_switch,
            )
        ),
    )

    current = "And the exact code?"

    result = service.send_message(
        chat_id=chat_id,
        content=current,
    )

    assert result.contextualized is True

    # The weak News switch changes domain state, but it does not contain
    # enough independent topic information to replace Borealis.
    assert (
        result.context_anchor_message_id
        == substantive_topic.message_id
    )

    assert (
        result.retrieval_query
        == substantive_topic.content
        + "\n"
        + current
    )

    assert (
        result.plan.mode
        is AdaptiveRetrievalMode.NEWS
    )

    assert (
        result.plan.reason
        is AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN
    )

    assert local.calls == []
    assert archive.calls == []
