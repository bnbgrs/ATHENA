"""Adaptive local retrieval routing over existing hardened chat services."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from athena.chat.direct import (
    DirectChatGenerationResult,
    DirectChatService,
)
from athena.chat.generation import ChatGenerationResult
from athena.chat.memory import (
    MemoryAugmentedChatService,
    MemoryChatGenerationResult,
)
from athena.chat.models import ChatMessage, MessageType
from athena.chat.news_grounding import (
    NewsGroundedChatResult,
    NewsGroundedChatService,
)
from athena.chat.research_grounding import (
    ResearchGroundedChatResult,
    ResearchGroundedChatService,
)
from athena.chat.service import ChatService
from athena.chat.source_grounding import (
    SourceGroundedChatResult,
    SourceGroundedChatService,
)
from athena.chat.unified import (
    UnifiedLocalChatResult,
    UnifiedLocalChatService,
)
from athena.memory.models import MemoryScopeKind
from athena.retrieval.archive import (
    ArchiveSearchError,
    ArchiveSearchService,
)
from athena.retrieval.lexical_relevance import required_term_matches
from athena.retrieval.news_events import (
    NewsEventSearchError,
    NewsEventSearchService,
)
from athena.retrieval.prior_research import (
    PriorResearchSearchError,
    PriorResearchSearchService,
)
from athena.retrieval.search import (
    LocalSearchService,
    SearchEntityType,
    SearchError,
)


class AdaptiveRetrievalMode(str, Enum):
    """Existing hardened chat paths selectable by the adaptive planner."""

    DIRECT = "direct"
    MEMORY = "memory"
    RESEARCH = "research"
    NEWS = "news"
    SOURCES = "sources"
    UNIFIED = "unified"


class AdaptivePlanReason(str, Enum):
    """Deterministic explanation for one adaptive route."""

    EXPLICIT_MEMORY_AND_SOURCE = "explicit_memory_and_source"
    EXPLICIT_SOURCE = "explicit_source"
    EXPLICIT_MEMORY = "explicit_memory"
    EXPLICIT_RESEARCH = "explicit_research"
    EXPLICIT_NEWS = "explicit_news"
    FOLLOWUP_INHERITED_DOMAIN = "followup_inherited_domain"
    CANONICAL_LEXICAL_HIT = "canonical_lexical_hit"
    RESEARCH_LEXICAL_HIT = "research_lexical_hit"
    NEWS_LEXICAL_HIT = "news_lexical_hit"
    ARCHIVE_LEXICAL_HIT = "archive_lexical_hit"
    NO_LOCAL_LEXICAL_HIT = "no_local_lexical_hit"
    NO_INFORMATIVE_QUERY_TERMS = "no_informative_query_terms"


@dataclass(frozen=True, slots=True)
class AdaptiveRetrievalPlan:
    """One transparent no-model routing decision."""

    mode: AdaptiveRetrievalMode
    reason: AdaptivePlanReason
    probe_query: str | None
    canonical_probe_hit: bool
    archive_probe_hit: bool
    warnings: tuple[str, ...]
    research_probe_hit: bool = False
    news_probe_hit: bool = False


@dataclass(frozen=True, slots=True)
class AdaptiveChatResult:
    """One adaptive turn delegated to exactly one hardened chat service."""

    plan: AdaptiveRetrievalPlan
    generation: ChatGenerationResult
    retrieval_query: str
    contextualized: bool
    context_anchor_message_id: uuid.UUID | None
    direct_result: DirectChatGenerationResult | None = None
    memory_result: MemoryChatGenerationResult | None = None
    research_result: ResearchGroundedChatResult | None = None
    news_result: NewsGroundedChatResult | None = None
    source_result: SourceGroundedChatResult | None = None
    unified_result: UnifiedLocalChatResult | None = None


_NEWS_PATTERNS = (
    re.compile(
        r"\b(?:news|nachrichten|meldung\w*|schlagzeilen|headlines)\b"
    ),
    re.compile(
        r"\b(?:aktuell\w*|neueste\w*|latest|recent)\b"
        r".*\b(?:entwicklung\w*|developments?|news|nachrichten)\b"
    ),
    re.compile(
        r"\b(?:entwicklung\w*|developments?)\b"
        r".*\b(?:aktuell\w*|neueste\w*|latest|recent)\b"
    ),
)


_RESEARCH_PATTERNS = (
    re.compile(
        r"\b(?:prior|previous|earlier)\s+research\b"
    ),
    re.compile(
        r"\b(?:frueher\w*|fr\u00fcher\w*|vorherig\w*)\s+"
        r"(?:recherche|research)\b"
    ),
    re.compile(
        r"\b(?:unsere\w*|our)\s+(?:recherche|research)\b"
    ),
    re.compile(
        r"\b(?:rechercheergebnis\w*|"
        r"research\s+(?:result\w*|finding\w*))\b"
    ),
    re.compile(
        r"\b(?:was\s+(?:ergab|zeigte)|what\s+did)\b.*"
        r"\b(?:recherche|research)\b"
    ),
)


_SOURCE_PATTERNS = (
    re.compile(r"\b(?:roharchiv|raw archive|source anchor|sourceanchor)\b"),
    re.compile(
        r"\b(?:importiert\w*|hochgeladen\w*|imported|uploaded)\b"
        r".*\b(?:pdf|dokument\w*|datei\w*|unterlagen|"
        r"document\w*|file\w*|report\w*|source\w*)\b"
    ),
    re.compile(
        r"\b(?:im|in|aus|laut)\s+"
        r"(?:(?:dem|der|den|einem|einer|diesem|dieser|diesen)\s+)?"
        r"(?:pdf|dokument\w*|datei\w*|bericht\w*|quelle\w*)\b"
    ),
    re.compile(
        r"\b(?:in|from|according to)\s+"
        r"(?:(?:the|my|this)\s+)?"
        r"(?:pdf|document\w*|file\w*|report\w*|source\w*|attachment\w*)\b"
    ),
    re.compile(
        r"\b(?:meine\w*|unsere\w*|my|our)\s+"
        r"(?:unterlagen|dokument\w*|datei\w*|quellen|"
        r"documents|files|sources|attachments)\b"
    ),
    re.compile(
        r"\b(?:des|der|dieses|dieser|this)\s+"
        r"(?:pdfs?|dokuments?|berichts?|reports?|documents?)\b"
    ),
    re.compile(
        r"\b(?:was\s+sagen|what\s+do)\s+"
        r"(?:die\s+|the\s+)?(?:quellen|sources)\b"
        r".*\b(?:dazu|darueber|\u00fcber\s+das|about\s+that)\b"
    ),
    re.compile(r"\.(?:pdf|docx?|html?)\b"),
)

_MEMORY_PATTERNS = (
    re.compile(r"\b(?:was\s+)?(?:wei\u00dft|weisst)\s+du\s+noch\b"),
    re.compile(r"\b(?:erinnerst\s+du\s+dich|erinnere\s+dich|remember)\b"),
    re.compile(
        r"\b(?:wir|we)\b.*\b"
        r"(?:besprochen|entschieden|festgelegt|beschlossen|vereinbart|geplant|"
        r"discussed|decided|agreed|planned)\b"
    ),
    re.compile(
        r"\b(?:personal memory|pers\u00f6nliches ged\u00e4chtnis|"
        r"persoenliches gedaechtnis)\b"
    ),
    re.compile(
        r"\b(?:kanonisches wissen|canonical knowledge|"
        r"lokal gespeichert|locally stored|athena lokal)\b"
    ),
    re.compile(
        r"\b(?:meine\w*|my)\s+"
        r"(?:pr\u00e4ferenz\w*|praeferenz\w*|vorliebe\w*|preferences?)\b"
    ),
)



_CONVERSATION_RECORD_PATTERNS = (
    re.compile(
        r"\bwas\s+habe\s+ich\s+dir\s+"
        r"(?:gesagt|erzaehlt|erz\u00e4hlt|geschrieben)\b"
    ),
    re.compile(
        r"\bwas\s+hast\s+du\s+(?:mir\s+)?"
        r"(?:gesagt|geschrieben)\b"
    ),
    re.compile(
        r"\bwas\s+haben\s+wir\s+.*"
        r"\b(?:besprochen|diskutiert)\b"
    ),
    re.compile(
        r"\b(?:im|in\s+diesem)\s+chat\b"
    ),
    re.compile(
        r"\bgespraechsverlauf\b"
    ),
    re.compile(
        r"\bgespr\u00e4chsverlauf\b"
    ),
    re.compile(
        r"\bwhat\s+did\s+i\s+tell\s+you\b"
    ),
    re.compile(
        r"\bwhat\s+did\s+you\s+(?:tell|say|write)\b"
    ),
    re.compile(
        r"\bwhat\s+did\s+we\s+.*"
        r"\b(?:discuss|talk\s+about)\b"
    ),
    re.compile(
        r"\b(?:chat|conversation)\s+history\b"
    ),
    re.compile(
        r"\b(?:earlier|previously)\s+in\s+"
        r"(?:this\s+)?(?:chat|conversation)\b"
    ),
)

_FOLLOWUP_LEADING_PATTERN = re.compile(
    r"^(?:und|and|aber|but|dann|then|also|"
    r"ausserdem|au\u00dferdem)\b"
)

_FOLLOWUP_EXACT_PATTERN = re.compile(
    r"^(?:warum|wieso|weshalb|wie|why|how|"
    r"genauer|details)\s*[?.!]*$"
)

_FOLLOWUP_REFERENCE_PATTERN = re.compile(
    r"\b(?:dazu|darueber|\u00fcber\s+das|damit|davon|"
    r"dies|diese|dieses|that|this|it|genauer)\b"
)

_FOLLOWUP_TRAILING_DAS_PATTERN = re.compile(
    r"\bdas\s*[?.!]*$"
)

_MAX_FOLLOWUP_ANCHOR_USER_TURNS = 8
_MAX_CONTEXTUALIZED_RETRIEVAL_QUERY_CHARS = 2048

_PROBE_STOPWORDS = frozenset(
    {
        "aber",
        "als",
        "also",
        "am",
        "an",
        "and",
        "are",
        "auch",
        "auf",
        "aus",
        "be",
        "bei",
        "bin",
        "bis",
        "bitte",
        "but",
        "by",
        "das",
        "dass",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "dies",
        "diese",
        "diesem",
        "diesen",
        "dieser",
        "do",
        "du",
        "ein",
        "eine",
        "einem",
        "einen",
        "einer",
        "er",
        "es",
        "for",
        "from",
        "f\u00fcr",
        "fuer",
        "hat",
        "have",
        "ich",
        "im",
        "in",
        "is",
        "ist",
        "it",
        "kann",
        "kannst",
        "man",
        "me",
        "mein",
        "meine",
        "meinen",
        "meiner",
        "mich",
        "mir",
        "mit",
        "my",
        "of",
        "oder",
        "on",
        "or",
        "our",
        "sein",
        "sind",
        "so",
        "the",
        "this",
        "to",
        "\u00fcber",
        "ueber",
        "und",
        "uns",
        "unser",
        "unsere",
        "von",
        "was",
        "we",
        "welche",
        "welcher",
        "welches",
        "wenn",
        "wer",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "warum",
        "weshalb",
        "why",
        "wie",
        "wieso",
        "wir",
        "beschreibe",
        "beschreiben",
        "contains",
        "draft",
        "enthaelt",
        "enth\u00e4lt",
        "erkl\u00e4re",
        "erkl\u00e4ren",
        "explain",
        "fasse",
        "formuliere",
        "generate",
        "generiere",
        "knowledge",
        "nenne",
        "nenn",
        "please",
        "project",
        "projekt",
        "sag",
        "sage",
        "sagen",
        "schreib",
        "schreibe",
        "show",
        "summarize",
        "tell",
        "translate",
        "uebersetze",
        "\u00fcbersetze",
        "wissen",
        "write",
        "zeige",
        "zeigen",
        "zusammen",
        "with",
        "wo",
        "you",
        "zu",
        "zum",
        "zur",
    }
)

# Generic routing/storage language carries little entity-level retrieval
# information. Keep it out of cross-domain probes so natural-language
# phrasing cannot inflate the relevance threshold artificially.
_PROBE_META_STOPWORDS = frozenset(
    {
        "according",
        "available",
        "data",
        "daten",
        "existing",
        "gespeichert",
        "local",
        "locally",
        "lokal",
        "laut",
        "stored",
        "vorhanden",
    }
)

# Narrow morphology handling for words that are already classified as
# probe noise. This intentionally is not a general-purpose stemmer:
# semantic query terms remain exact.
_PROBE_STOPWORD_INFLECTION_SUFFIXES = (
    "ern",
    "em",
    "en",
    "er",
    "es",
    "e",
    "s",
)

_MAX_PROBE_TERMS = 12
_MAX_RESERVED_DISTINCTIVE_PROBE_TERMS = 4

# A matched opaque identifier may compensate for at most two otherwise
# unmatched terms in a long natural-language probe. It can never make a
# candidate relevant by itself.
_DISTINCTIVE_PROBE_MATCH_BONUS = 2


class AdaptiveRetrievalPlanner:
    """Choose the smallest mature local retrieval domain required for one turn."""

    def __init__(
        self,
        *,
        local_search: LocalSearchService,
        archive_search: ArchiveSearchService,
        prior_research: PriorResearchSearchService | None = None,
        news_events: NewsEventSearchService | None = None,
    ) -> None:
        self.local_search = local_search
        self.archive_search = archive_search
        self.prior_research = prior_research
        self.news_events = news_events

    def explicit_plan(
        self,
        content: str,
    ) -> AdaptiveRetrievalPlan | None:
        """Return an explicit user-selected local domain without storage probes."""

        normalized = _normalize_for_matching(
            content
        )

        explicit_source = _matches_any(
            normalized,
            _SOURCE_PATTERNS,
        )

        explicit_memory = _matches_any(
            normalized,
            _MEMORY_PATTERNS,
        )

        explicit_research = _matches_any(
            normalized,
            _RESEARCH_PATTERNS,
        )

        explicit_news = _matches_any(
            normalized,
            _NEWS_PATTERNS,
        )

        if explicit_memory and explicit_source:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.UNIFIED,
                reason=AdaptivePlanReason.EXPLICIT_MEMORY_AND_SOURCE,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
            )

        if explicit_research:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.RESEARCH,
                reason=AdaptivePlanReason.EXPLICIT_RESEARCH,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
                research_probe_hit=False,
            )

        if explicit_source:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.SOURCES,
                reason=AdaptivePlanReason.EXPLICIT_SOURCE,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
            )

        if explicit_news:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.NEWS,
                reason=AdaptivePlanReason.EXPLICIT_NEWS,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
                news_probe_hit=False,
            )

        if explicit_memory:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.MEMORY,
                reason=AdaptivePlanReason.EXPLICIT_MEMORY,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
            )

        return None

    def plan(
        self,
        content: str,
    ) -> AdaptiveRetrievalPlan:
        explicit = self.explicit_plan(
            content
        )

        if explicit is not None:
            return explicit

        probe_terms = _probe_terms(
            content
        )

        probe_query = (
            " ".join(probe_terms)
            if probe_terms
            else None
        )

        if probe_query is None:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.DIRECT,
                reason=AdaptivePlanReason.NO_INFORMATIVE_QUERY_TERMS,
                probe_query=None,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=(),
            )

        warnings: list[str] = []
        canonical_hit = False

        try:
            knowledge = self.local_search.search(
                probe_query,
                limit=5,
                entity_type=SearchEntityType.KNOWLEDGE,
            )

            canonical_hit = any(
                _supports_probe_terms(
                    probe_terms,
                    title=item.title,
                    text=item.text,
                )
                for item in knowledge
            )

            if not canonical_hit:
                claims = self.local_search.search(
                    probe_query,
                    limit=5,
                    entity_type=SearchEntityType.CLAIM,
                )

                canonical_hit = any(
                    _supports_probe_terms(
                        probe_terms,
                        title=item.title,
                        text=item.text,
                    )
                    for item in claims
                )

        except SearchError as exc:
            warnings.append(
                "canonical_probe_unavailable:"
                f"{type(exc).__name__}:{exc}"
            )

        if canonical_hit:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.MEMORY,
                reason=AdaptivePlanReason.CANONICAL_LEXICAL_HIT,
                probe_query=probe_query,
                canonical_probe_hit=True,
                archive_probe_hit=False,
                warnings=tuple(warnings),
            )

        research_hit = False

        if self.prior_research is not None:
            try:
                research = self.prior_research.search(
                    probe_query,
                    limit=5,
                )

                research_hit = any(
                    _supports_probe_terms(
                        probe_terms,
                        title=None,
                        text=item.text,
                    )
                    for item in research
                )

            except PriorResearchSearchError as exc:
                warnings.append(
                    "research_probe_unavailable:"
                    f"{type(exc).__name__}:{exc}"
                )

        if research_hit:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.RESEARCH,
                reason=AdaptivePlanReason.RESEARCH_LEXICAL_HIT,
                probe_query=probe_query,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=tuple(warnings),
                research_probe_hit=True,
            )

        news_hit = False

        if self.news_events is not None:
            try:
                news = self.news_events.search(
                    probe_query,
                    limit=5,
                )
                news_hit = any(
                    _supports_probe_terms(
                        probe_terms,
                        title=None,
                        text=item.text,
                    )
                    for item in news
                )
            except NewsEventSearchError as exc:
                warnings.append(
                    "news_probe_unavailable:"
                    f"{type(exc).__name__}:{exc}"
                )

        if news_hit:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.NEWS,
                reason=AdaptivePlanReason.NEWS_LEXICAL_HIT,
                probe_query=probe_query,
                canonical_probe_hit=False,
                archive_probe_hit=False,
                warnings=tuple(warnings),
                research_probe_hit=False,
                news_probe_hit=True,
            )

        archive_hit = False

        try:
            archive = self.archive_search.search(
                probe_query,
                limit=5,
            )

            archive_hit = any(
                _supports_probe_terms(
                    probe_terms,
                    title=item.source_name,
                    text=item.text,
                )
                for item in archive
            )

        except ArchiveSearchError as exc:
            warnings.append(
                "archive_probe_unavailable:"
                f"{type(exc).__name__}:{exc}"
            )

        if archive_hit:
            return AdaptiveRetrievalPlan(
                mode=AdaptiveRetrievalMode.SOURCES,
                reason=AdaptivePlanReason.ARCHIVE_LEXICAL_HIT,
                probe_query=probe_query,
                canonical_probe_hit=False,
                archive_probe_hit=True,
                warnings=tuple(warnings),
            )

        return AdaptiveRetrievalPlan(
            mode=AdaptiveRetrievalMode.DIRECT,
            reason=AdaptivePlanReason.NO_LOCAL_LEXICAL_HIT,
            probe_query=probe_query,
            canonical_probe_hit=False,
            archive_probe_hit=False,
            warnings=tuple(warnings),
        )


class AdaptiveChatService:
    """Contextualize follow-ups, then delegate exactly one complete chat turn."""

    def __init__(
        self,
        *,
        chat: ChatService,
        planner: AdaptiveRetrievalPlanner,
        direct_chat: DirectChatService,
        memory_chat: MemoryAugmentedChatService,
        source_grounded_chat: SourceGroundedChatService,
        unified_local_chat: UnifiedLocalChatService,
        research_grounded_chat: ResearchGroundedChatService | None = None,
        news_grounded_chat: NewsGroundedChatService | None = None,
    ) -> None:
        self.chat = chat
        self.planner = planner
        self.direct_chat = direct_chat
        self.memory_chat = memory_chat
        self.source_grounded_chat = source_grounded_chat
        self.unified_local_chat = unified_local_chat
        self.research_grounded_chat = research_grounded_chat
        self.news_grounded_chat = news_grounded_chat

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        max_memory_context_tokens: int = 1200,
        max_memory_context_items: int = 8,
        max_memory_items: int = 8,
        max_source_context_tokens: int = 1200,
        max_source_context_items: int = 8,
        max_research_context_tokens: int = 1200,
        max_research_context_items: int = 8,
        max_news_context_tokens: int = 1200,
        max_news_context_items: int = 8,
        memory_scope_kind: MemoryScopeKind | None = None,
        memory_scope_entity_id: uuid.UUID | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = 2048,
        safety_margin: int = 256,
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> AdaptiveChatResult:
        retrieval_query = content
        contextualized = False
        anchor: ChatMessage | None = None

        if _looks_like_followup(content):
            explicit_current = self.planner.explicit_plan(
                content
            )

            thread = self.chat.load_chat(
                chat_id
            )

            anchor = self._select_followup_anchor(
                thread.messages
            )

            if anchor is not None:
                anchor_content = anchor.content

                if anchor_content is None:
                    raise RuntimeError(
                        "Adaptive follow-up anchor has unavailable content."
                    )

                retrieval_query = _compose_followup_retrieval_query(
                    anchor_content,
                    content,
                )

                contextualized = True

                if explicit_current is not None:
                    plan = explicit_current
                else:
                    inherited = self._select_followup_domain_plan(
                        thread.messages,
                        anchor=anchor,
                    )

                    if inherited is not None:
                        plan = AdaptiveRetrievalPlan(
                            mode=inherited.mode,
                            reason=AdaptivePlanReason.FOLLOWUP_INHERITED_DOMAIN,
                            probe_query=None,
                            canonical_probe_hit=False,
                            archive_probe_hit=False,
                            warnings=(),
                        )
                    else:
                        plan = self.planner.plan(
                            retrieval_query
                        )
            else:
                plan = (
                    explicit_current
                    if explicit_current is not None
                    else self.planner.plan(content)
                )
        else:
            plan = self.planner.plan(
                content
            )

        retrieval_override = (
            retrieval_query
            if contextualized
            else None
        )

        anchor_id = (
            anchor.message_id
            if anchor is not None
            else None
        )

        if plan.mode is AdaptiveRetrievalMode.DIRECT:
            direct_result = self.direct_chat.send_message(
                chat_id=chat_id,
                content=content,
                requested_model_id=requested_model_id,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=direct_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                direct_result=direct_result,
            )

        if plan.mode is AdaptiveRetrievalMode.MEMORY:
            memory_result = self.memory_chat.send_message(
                chat_id=chat_id,
                content=content,
                retrieval_query=retrieval_override,
                canonical_only_retrieval=(
                    not _requires_conversation_record_retrieval(
                        retrieval_query
                    )
                ),
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                max_context_tokens=max_memory_context_tokens,
                max_context_items=max_memory_context_items,
                max_memory_items=max_memory_items,
                memory_scope_kind=memory_scope_kind,
                memory_scope_entity_id=memory_scope_entity_id,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                allow_model_prior=allow_model_prior,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=memory_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                memory_result=memory_result,
            )

        if plan.mode is AdaptiveRetrievalMode.RESEARCH:
            if self.research_grounded_chat is None:
                raise RuntimeError(
                    "Adaptive Research route is not configured."
                )

            research_result = self.research_grounded_chat.send_message(
                chat_id=chat_id,
                content=content,
                retrieval_query=retrieval_override,
                requested_model_id=requested_model_id,
                max_context_tokens=max_research_context_tokens,
                max_context_items=max_research_context_items,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                allow_model_prior=allow_model_prior,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=research_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                research_result=research_result,
            )

        if plan.mode is AdaptiveRetrievalMode.NEWS:
            if self.news_grounded_chat is None:
                raise RuntimeError(
                    "Adaptive News route is not configured."
                )

            news_result = self.news_grounded_chat.send_message(
                chat_id=chat_id,
                content=content,
                retrieval_query=retrieval_override,
                requested_model_id=requested_model_id,
                max_context_tokens=max_news_context_tokens,
                max_context_items=max_news_context_items,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                allow_model_prior=allow_model_prior,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=news_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                news_result=news_result,
            )

        if plan.mode is AdaptiveRetrievalMode.SOURCES:
            source_result = self.source_grounded_chat.send_message(
                chat_id=chat_id,
                content=content,
                retrieval_query=retrieval_override,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                max_context_tokens=max_source_context_tokens,
                max_context_items=max_source_context_items,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                allow_model_prior=allow_model_prior,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=source_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                source_result=source_result,
            )

        if plan.mode is AdaptiveRetrievalMode.UNIFIED:
            unified_result = self.unified_local_chat.send_message(
                chat_id=chat_id,
                content=content,
                retrieval_query=retrieval_override,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                max_memory_context_tokens=max_memory_context_tokens,
                max_memory_context_items=max_memory_context_items,
                max_memory_items=max_memory_items,
                max_source_context_tokens=max_source_context_tokens,
                max_source_context_items=max_source_context_items,
                memory_scope_kind=memory_scope_kind,
                memory_scope_entity_id=memory_scope_entity_id,
                effective_context_limit=effective_context_limit,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                allow_model_prior=allow_model_prior,
                on_delta=on_delta,
            )

            return AdaptiveChatResult(
                plan=plan,
                generation=unified_result.generation,
                retrieval_query=retrieval_query,
                contextualized=contextualized,
                context_anchor_message_id=anchor_id,
                unified_result=unified_result,
            )

        raise RuntimeError(
            f"Unsupported adaptive retrieval mode: {plan.mode!r}"
        )

    def _select_followup_domain_plan(
        self,
        messages: tuple[ChatMessage, ...],
        *,
        anchor: ChatMessage,
    ) -> AdaptiveRetrievalPlan | None:
        """Return the newest explicit domain selection for this topic.

        Content anchoring and domain inheritance are intentionally separate.

        The substantive content anchor may predate one or more short
        follow-ups. An explicit domain switch inside those follow-ups must
        become authoritative for subsequent route inheritance, but an
        explicit route from an older topic must never leak across a newer
        substantive anchor.
        """

        for message in reversed(messages):
            if message.message_type is not MessageType.USER:
                continue

            if message.sequence_no < anchor.sequence_no:
                break

            content = message.content

            if content is None:
                continue

            normalized = content.strip()

            if not normalized:
                continue

            explicit = self.planner.explicit_plan(
                normalized
            )

            if explicit is not None:
                return explicit

        return None

    def _select_followup_anchor(
        self,
        messages: tuple[ChatMessage, ...],
    ) -> ChatMessage | None:
        """Return the best topic anchor for one anaphoric follow-up.

        Content anchoring and domain inheritance are independent.

        A normal substantive user turn is a valid topic anchor. An explicit
        routing turn that is linguistically a follow-up can also become the
        new topic anchor when it contains at least three informative probe
        terms. This prevents a self-contained cross-topic domain switch from
        inheriting an older topic accidentally.

        Weak explicit routing turns keep the older substantive topic anchor.
        If no substantive topic exists, the newest explicit turn is retained
        as a last-resort content anchor.
        """

        user_turns = 0
        explicit_fallback: ChatMessage | None = None

        for message in reversed(messages):
            if message.message_type is not MessageType.USER:
                continue

            user_turns += 1

            if user_turns > _MAX_FOLLOWUP_ANCHOR_USER_TURNS:
                break

            content = message.content

            if content is None:
                continue

            normalized = content.strip()

            if not normalized:
                continue

            explicit = self.planner.explicit_plan(
                normalized
            )

            probe_terms = _probe_terms(
                normalized
            )

            if (
                explicit is not None
                and explicit_fallback is None
            ):
                explicit_fallback = message

            if _looks_like_followup(
                normalized
            ):
                if (
                    explicit is not None
                    and len(probe_terms) >= 3
                ):
                    return message

                continue

            if (
                explicit is not None
                or probe_terms
            ):
                return message

        return explicit_fallback


def _requires_conversation_record_retrieval(
    content: str,
) -> bool:
    return _matches_any(
        _normalize_for_matching(content),
        _CONVERSATION_RECORD_PATTERNS,
    )


def _looks_like_followup(
    content: str,
) -> bool:
    normalized = _normalize_for_matching(
        content
    )

    if not normalized:
        return False

    if _FOLLOWUP_LEADING_PATTERN.search(
        normalized
    ):
        return True

    if _FOLLOWUP_EXACT_PATTERN.fullmatch(
        normalized
    ):
        return True

    tokens = re.findall(
        r"\w+",
        normalized,
        flags=re.UNICODE,
    )

    if len(tokens) <= 12:
        if _FOLLOWUP_REFERENCE_PATTERN.search(
            normalized
        ):
            return True

        if _FOLLOWUP_TRAILING_DAS_PATTERN.search(
            normalized
        ):
            return True

    return False


def _compose_followup_retrieval_query(
    anchor_content: str,
    current_content: str,
) -> str:
    anchor = anchor_content.strip()
    current = current_content.strip()

    combined = (
        f"{anchor}\n{current}"
    )

    if (
        len(combined)
        <= _MAX_CONTEXTUALIZED_RETRIEVAL_QUERY_CHARS
    ):
        return combined

    selected: list[str] = []
    seen: set[str] = set()

    for term in (
        *_probe_terms(anchor),
        *_probe_terms(current),
    ):
        if term in seen:
            continue

        candidate = " ".join(
            (*selected, term)
        )

        if (
            len(candidate)
            > _MAX_CONTEXTUALIZED_RETRIEVAL_QUERY_CHARS
        ):
            break

        seen.add(term)
        selected.append(term)

    if selected:
        return " ".join(
            selected
        )

    return current[
        :_MAX_CONTEXTUALIZED_RETRIEVAL_QUERY_CHARS
    ]


def _matches_any(
    normalized: str,
    patterns: tuple[re.Pattern[str], ...],
) -> bool:
    return any(
        pattern.search(normalized)
        is not None
        for pattern in patterns
    )


def _normalize_for_matching(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    return " ".join(
        normalized.split()
    )


def _is_probe_stopword(
    token: str,
) -> bool:
    if (
        token in _PROBE_STOPWORDS
        or token in _PROBE_META_STOPWORDS
    ):
        return True

    for suffix in _PROBE_STOPWORD_INFLECTION_SUFFIXES:
        if len(token) <= len(suffix) + 2:
            continue

        stem = token[: -len(suffix)]

        if (
            stem in _PROBE_STOPWORDS
            or stem in _PROBE_META_STOPWORDS
        ):
            return True

    return False


def _is_distinctive_probe_term(
    term: str,
) -> bool:
    if len(term) < 5:
        return False

    return (
        any(character.isalpha() for character in term)
        and any(character.isdigit() for character in term)
    )


def _probe_terms(
    value: str,
) -> tuple[str, ...]:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    tokens = re.findall(
        r"\w+",
        normalized,
        flags=re.UNICODE,
    )

    candidates: list[str] = []
    seen: set[str] = set()

    for token in tokens:
        if _is_probe_stopword(token):
            continue

        if len(token) < 2:
            continue

        if token in seen:
            continue

        seen.add(token)
        candidates.append(token)

    if len(candidates) <= _MAX_PROBE_TERMS:
        return tuple(candidates)

    # Preserve a bounded number of opaque identifiers even when they occur
    # late in a verbose user query. Without this reservation, the old
    # first-N policy could discard the strongest local entity key.
    reserved_indices: list[int] = []

    for index, term in enumerate(candidates):
        if not _is_distinctive_probe_term(term):
            continue

        reserved_indices.append(index)

        if (
            len(reserved_indices)
            >= _MAX_RESERVED_DISTINCTIVE_PROBE_TERMS
        ):
            break

    selected_indices = set(reserved_indices)

    for index in range(len(candidates)):
        if len(selected_indices) >= _MAX_PROBE_TERMS:
            break

        selected_indices.add(index)

    return tuple(
        candidates[index]
        for index in sorted(selected_indices)
    )


def _build_probe_query(
    value: str,
) -> str | None:
    terms = _probe_terms(value)

    if not terms:
        return None

    return " ".join(terms)


def _candidate_tokens(
    *values: str | None,
) -> frozenset[str]:
    tokens: set[str] = set()

    for value in values:
        if not value:
            continue

        normalized = unicodedata.normalize(
            "NFKC",
            value,
        ).casefold()

        tokens.update(
            re.findall(
                r"\w+",
                normalized,
                flags=re.UNICODE,
            )
        )

    return frozenset(tokens)


def _supports_probe_terms(
    probe_terms: tuple[str, ...],
    *,
    title: str | None,
    text: str,
) -> bool:
    if not probe_terms:
        return False

    candidate = _candidate_tokens(
        title,
        text,
    )

    matched_terms = tuple(
        term
        for term in probe_terms
        if term in candidate
    )

    matched = len(matched_terms)

    required = required_term_matches(
        len(probe_terms)
    )

    if matched >= required:
        return True

    # Short probes remain fully conservative. Their existing exact/near-exact
    # semantics must not be weakened by identifier heuristics.
    if len(probe_terms) <= 3:
        return False

    distinctive_matches = sum(
        1
        for term in matched_terms
        if _is_distinctive_probe_term(term)
    )

    non_distinctive_matches = (
        matched - distinctive_matches
    )

    # One opaque identifier alone must never turn an otherwise unrelated
    # candidate into a routing hit.
    if (
        distinctive_matches < 1
        or non_distinctive_matches < 2
    ):
        return False

    credited_matches = (
        matched
        + _DISTINCTIVE_PROBE_MATCH_BONUS
    )

    return credited_matches >= required
