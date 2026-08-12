"""ATHENA application lifecycle coordinator."""

from __future__ import annotations

import logging
from enum import Enum

from athena.chat.generation import ChatGenerationService
from athena.chat.memory import MemoryAugmentedChatService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.config.settings import AthenaSettings
from athena.core.services import LifecycleService, ServiceManager
from athena.knowledge.acceptance_service import ProposalAcceptanceService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.claim_service import ClaimService
from athena.knowledge.extraction_service import ChatKnowledgeExtractionService
from athena.knowledge.extraction_snapshot import ExtractionSnapshotRepository
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.review_service import ReviewService
from athena.knowledge.service import KnowledgeService
from athena.model.adapters.lm_studio import LMStudioProvider
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.provenance import ModelRunRepository
from athena.observability.health import HealthService
from athena.observability.logging import configure_logging
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.evidence import MemoryEvidencePolicy
from athena.retrieval.hybrid import HybridRetrievalService
from athena.retrieval.ranking import RetrievalRankingService
from athena.retrieval.search import LocalSearchService
from athena.retrieval.semantic import LocalSemanticSearchService
from athena.storage.database import SQLiteDatabase
from athena.storage.paths import RuntimePaths
from athena.storage.runtime import RuntimeLayoutService

logger = logging.getLogger(__name__)


class ApplicationState(str, Enum):
    """Lifecycle states of the local ATHENA Core."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class AthenaApplication:
    """Failure-aware Phase-0 ATHENA Core."""

    def __init__(
        self,
        settings: AthenaSettings | None = None,
        services: tuple[LifecycleService, ...] = (),
    ) -> None:
        self.settings = settings or AthenaSettings.from_environment()
        self.paths = RuntimePaths.from_settings(self.settings)
        self.state = ApplicationState.STOPPED
        self.health = HealthService()
        self.database = SQLiteDatabase(self.paths.database_path)
        self.chat_repository = ChatRepository(self.database)
        self.chat = ChatService(self.chat_repository)
        self.knowledge_repository = KnowledgeRepository(self.database)
        self.knowledge = KnowledgeService(self.knowledge_repository, self.chat)
        self.claim_repository = ClaimRepository(self.database)
        self.claims = ClaimService(self.claim_repository, self.chat)
        self.model_provider = LMStudioProvider(
            base_url=self.settings.lm_studio_base_url,
            timeout_seconds=self.settings.model_request_timeout_seconds,
            generation_timeout_seconds=self.settings.model_generation_timeout_seconds,
        )
        self.chat_generation = ChatGenerationService(self.chat, self.model_provider)
        self.embedding_provider = LMStudioEmbeddingProvider(
            self.model_provider,
            generation_timeout_seconds=self.settings.model_generation_timeout_seconds,
        )
        self.model_runs = ModelRunRepository(self.database)
        self.reviews = ReviewService(self.database)
        self.extraction_snapshots = ExtractionSnapshotRepository(
            self.database, self.model_runs
        )
        self.extraction = ChatKnowledgeExtractionService(
            chat=self.chat,
            chat_generation=self.chat_generation,
            provider=self.model_provider,
            runs=self.model_runs,
            snapshots=self.extraction_snapshots,
        )
        self.search = LocalSearchService(self.database)
        self.retrieval = RetrievalRankingService(self.search)
        self.semantic_search = LocalSemanticSearchService(
            self.database,
            self.embedding_provider,
        )
        self.hybrid_retrieval = HybridRetrievalService(
            self.retrieval,
            self.semantic_search,
        )
        self.context_builder = ContextBuilderService()
        self.memory_evidence_policy = MemoryEvidencePolicy(self.database)
        self.memory_chat = MemoryAugmentedChatService(
            chat_generation=self.chat_generation,
            embedding_provider=self.embedding_provider,
            hybrid_retrieval=self.hybrid_retrieval,
            context_builder=self.context_builder,
            evidence_policy=self.memory_evidence_policy,
        )
        self.proposal_acceptance = ProposalAcceptanceService(
            database=self.database,
            chat=self.chat,
            knowledge=self.knowledge_repository,
            claims=self.claim_repository,
            reviews=self.reviews,
        )

        bootstrap_services: tuple[LifecycleService, ...] = (
            RuntimeLayoutService(self.paths),
            self.database,
        )
        self.services = ServiceManager(bootstrap_services + services)

    def start(self) -> None:
        """Start ATHENA and all registered services safely."""
        if self.state is ApplicationState.RUNNING:
            return
        if self.state is not ApplicationState.STOPPED:
            raise RuntimeError(
                f"Cannot start ATHENA from state {self.state.value!r}."
            )

        self.state = ApplicationState.STARTING
        self.health.mark_starting()
        configure_logging(self.settings.numeric_log_level)

        logger.info("ATHENA Core starting", extra={"event": "core.starting"})

        try:
            self.services.start_all()
        except Exception as exc:
            self.state = ApplicationState.FAILED
            self.health.mark_failed(str(exc))
            logger.exception(
                "ATHENA Core startup failed",
                extra={"event": "core.start_failed"},
            )
            raise

        self.state = ApplicationState.RUNNING
        self.health.mark_ok()
        logger.info("ATHENA Core running", extra={"event": "core.running"})

    def stop(self) -> None:
        """Stop ATHENA and all registered services safely."""
        if self.state is ApplicationState.STOPPED:
            return
        if self.state not in {
            ApplicationState.RUNNING,
            ApplicationState.FAILED,
        }:
            raise RuntimeError(
                f"Cannot stop ATHENA from state {self.state.value!r}."
            )

        self.state = ApplicationState.STOPPING
        self.health.mark_stopping()
        logger.info("ATHENA Core stopping", extra={"event": "core.stopping"})

        try:
            self.services.stop_all()
        except Exception as exc:
            self.state = ApplicationState.FAILED
            self.health.mark_failed(str(exc))
            logger.exception(
                "ATHENA Core shutdown failed",
                extra={"event": "core.stop_failed"},
            )
            raise

        self.state = ApplicationState.STOPPED
        self.health.mark_stopped()
        logger.info("ATHENA Core stopped", extra={"event": "core.stopped"})
