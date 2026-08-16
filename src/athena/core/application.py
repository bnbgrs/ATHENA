"""ATHENA application lifecycle coordinator."""

from __future__ import annotations

import logging
from enum import Enum

from athena.backup.service import BackupService
from athena.chat.adaptive import (
    AdaptiveChatService,
    AdaptiveRetrievalPlanner,
)
from athena.chat.direct import DirectChatService
from athena.chat.generation import ChatGenerationService
from athena.chat.memory import MemoryAugmentedChatService
from athena.chat.news_grounding import NewsGroundedChatService
from athena.chat.repository import ChatRepository
from athena.chat.research_grounding import ResearchGroundedChatService
from athena.chat.service import ChatService
from athena.chat.source_grounding import SourceGroundedChatService
from athena.chat.unified import UnifiedLocalChatService
from athena.config.settings import AthenaSettings
from athena.core.services import LifecycleService, ServiceManager
from athena.external.gateway import ExternalAccessGateway, ExternalResearchService
from athena.jobs.embedding_processing import DurableEmbeddingRebuildWorker
from athena.jobs.repository import JobRepository
from athena.jobs.research import DurableResearchWorker
from athena.jobs.scheduler import DurableJobScheduler
from athena.jobs.service import DurableJobService
from athena.jobs.source_analysis import DurableSourceAnalysisWorker
from athena.jobs.source_extraction import DurableSourceHierarchicalExtractionWorker
from athena.jobs.source_processing import DurableSourceProcessingWorker
from athena.knowledge.acceptance_service import ProposalAcceptanceService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.claim_service import ClaimService
from athena.knowledge.extraction_service import ChatKnowledgeExtractionService
from athena.knowledge.extraction_snapshot import ExtractionSnapshotRepository
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.review_service import ReviewService
from athena.knowledge.service import KnowledgeService
from athena.knowledge.source_acceptance import SourceProposalAcceptanceService
from athena.knowledge.source_extraction import (
    SourceAnalysisKnowledgeExtractionService,
    SourceExtractionSnapshotRepository,
)
from athena.knowledge.source_hierarchical_repository import (
    SourceHierarchicalExtractionRepository,
)
from athena.knowledge.source_hierarchical_service import SourceHierarchicalExtractionService
from athena.memory.repository import PersonalMemoryRepository
from athena.memory.service import PersonalMemoryService
from athena.model.adapters.lm_studio import LMStudioProvider
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.provenance import ModelRunRepository
from athena.news.service import NewsService
from athena.observability.health import HealthService
from athena.observability.logging import configure_logging
from athena.research.promotion import ResearchPromotionService
from athena.research.repository import ResearchRepository
from athena.research.service import ResearchService
from athena.research.synthesis_service import ResearchSynthesisService
from athena.resources.manager import ResourceManager
from athena.retrieval.archive import (
    ArchiveHybridRetrievalService,
    ArchiveSearchService,
    ArchiveSemanticSearchService,
)
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.context_package import ContextPackageService
from athena.retrieval.evidence import MemoryEvidencePolicy
from athena.retrieval.hybrid import HybridRetrievalService
from athena.retrieval.news_events import (
    NewsEventContextBuilderService,
    NewsEventSearchService,
)
from athena.retrieval.prior_research import (
    PriorResearchContextBuilderService,
    PriorResearchSearchService,
)
from athena.retrieval.ranking import RetrievalRankingService
from athena.retrieval.search import LocalSearchService
from athena.retrieval.semantic import LocalSemanticSearchService
from athena.retrieval.source_context import SourceContextBuilderService
from athena.source.analysis_repository import SourceAnalysisRepository
from athena.source.analysis_service import SourceAnalysisService
from athena.source.anchor_repository import SourceAnchorRepository
from athena.source.anchor_service import SourceAnchorService
from athena.source.blob_store import BlobStore
from athena.source.chunk_store import SourceChunkStore
from athena.source.chunking_repository import ChunkingProfileRepository
from athena.source.chunking_service import SourceChunkingService
from athena.source.docx_representation_service import SourceDocxRepresentationService
from athena.source.docx_representation_store import DocxNativeTextRepresentationStore
from athena.source.html_representation_service import SourceHtmlRepresentationService
from athena.source.html_representation_store import HtmlNativeTextRepresentationStore
from athena.source.pdf_representation_service import SourcePdfRepresentationService
from athena.source.pdf_representation_store import PdfNativeTextRepresentationStore
from athena.source.repository import SourceRepository
from athena.source.representation_repository import SourceRepresentationRepository
from athena.source.representation_service import SourceTextRepresentationService
from athena.source.representation_store import TextRepresentationStore
from athena.source.service import SourceCaptureService
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
        self.personal_memory_repository = PersonalMemoryRepository(self.database)
        self.personal_memory = PersonalMemoryService(self.personal_memory_repository, self.chat)
        self.job_repository = JobRepository(self.database)
        self.jobs = DurableJobService(self.job_repository, self.chat)
        self.research_repository = ResearchRepository(self.database)
        self.blob_store = BlobStore(self.paths)
        self.source_repository = SourceRepository(self.database)
        self.source_representation_repository = SourceRepresentationRepository(self.database)
        self.source_anchor_repository = SourceAnchorRepository(self.database)
        self.chunking_profiles = ChunkingProfileRepository(self.database)
        self.source_chunk_store = SourceChunkStore(self.paths.derived_root)
        self.text_representation_store = TextRepresentationStore(self.paths)
        self.pdf_representation_store = PdfNativeTextRepresentationStore(self.paths)
        self.docx_representation_store = DocxNativeTextRepresentationStore(self.paths)
        self.html_representation_store = HtmlNativeTextRepresentationStore(self.paths)
        self.sources = SourceCaptureService(
            repository=self.source_repository,
            blob_store=self.blob_store,
            chat=self.chat,
        )
        self.backup = BackupService(
            database=self.database,
            blob_store=self.blob_store,
            paths=self.paths,
            chat=self.chat,
        )
        self.external_access = ExternalAccessGateway(
            database=self.database,
            chat=self.chat,
            sources=self.sources,
            paths=self.paths,
        )
        self.knowledge_repository = KnowledgeRepository(self.database)
        self.knowledge = KnowledgeService(self.knowledge_repository, self.chat)
        self.claim_repository = ClaimRepository(self.database)
        self.claims = ClaimService(self.claim_repository, self.chat)
        self.model_provider = LMStudioProvider(
            base_url=self.settings.lm_studio_base_url,
            timeout_seconds=self.settings.model_request_timeout_seconds,
            generation_timeout_seconds=self.settings.model_generation_timeout_seconds,
        )
        self.resources = ResourceManager(
            database=self.database,
            paths=self.paths,
            chat=self.chat,
            model_provider=self.model_provider,
            interactive_lease_seconds=max(
                60,
                int(self.settings.model_generation_timeout_seconds) + 60,
            ),
        )
        self.chat_generation = ChatGenerationService(
            self.chat,
            self.model_provider,
            interactive_demand=self.resources,
        )
        self.embedding_provider = LMStudioEmbeddingProvider(
            self.model_provider,
            generation_timeout_seconds=self.settings.model_generation_timeout_seconds,
        )
        self.model_runs = ModelRunRepository(self.database)
        self.context_packages = ContextPackageService(self.database)
        self.direct_chat = DirectChatService(
            chat_generation=self.chat_generation,
            context_packages=self.context_packages,
            model_runs=self.model_runs,
        )
        self.prior_research_search = PriorResearchSearchService(
            self.database
        )
        self.prior_research_context_builder = (
            PriorResearchContextBuilderService(
                self.prior_research_search
            )
        )
        self.research_grounded_chat = ResearchGroundedChatService(
            chat_generation=self.chat_generation,
            retrieval=self.prior_research_search,
            context_builder=self.prior_research_context_builder,
            context_packages=self.context_packages,
            model_runs=self.model_runs,
        )
        self.news_event_search = NewsEventSearchService(
            self.database
        )
        self.news_event_context_builder = NewsEventContextBuilderService(
            self.news_event_search
        )
        self.news_grounded_chat = NewsGroundedChatService(
            chat_generation=self.chat_generation,
            retrieval=self.news_event_search,
            context_builder=self.news_event_context_builder,
            context_packages=self.context_packages,
            model_runs=self.model_runs,
        )
        self.source_text = SourceTextRepresentationService(
            sources=self.source_repository,
            representations=self.source_representation_repository,
            blob_store=self.blob_store,
            representation_store=self.text_representation_store,
            runs=self.model_runs,
            chat=self.chat,
        )
        self.source_pdf = SourcePdfRepresentationService(
            sources=self.source_repository,
            representations=self.source_representation_repository,
            blob_store=self.blob_store,
            representation_store=self.pdf_representation_store,
            runs=self.model_runs,
            chat=self.chat,
        )
        self.source_docx = SourceDocxRepresentationService(
            sources=self.source_repository,
            representations=self.source_representation_repository,
            blob_store=self.blob_store,
            representation_store=self.docx_representation_store,
            runs=self.model_runs,
            chat=self.chat,
        )
        self.source_html = SourceHtmlRepresentationService(
            sources=self.source_repository,
            representations=self.source_representation_repository,
            blob_store=self.blob_store,
            representation_store=self.html_representation_store,
            runs=self.model_runs,
            chat=self.chat,
        )
        self.source_chunks = SourceChunkingService(
            source_text=self.source_text,
            profiles=self.chunking_profiles,
            store=self.source_chunk_store,
            runs=self.model_runs,
            chat=self.chat,
        )
        self.source_anchors = SourceAnchorService(
            repository=self.source_anchor_repository,
            source_text=self.source_text,
            source_chunks=self.source_chunks,
            chunk_store=self.source_chunk_store,
            chat=self.chat,
        )
        self.archive_search = ArchiveSearchService(
            database=self.database,
            chunk_store=self.source_chunk_store,
            source_chunks=self.source_chunks,
        )
        self.archive_semantic_search = ArchiveSemanticSearchService(
            lexical=self.archive_search,
            provider=self.embedding_provider,
        )
        self.archive_hybrid_retrieval = ArchiveHybridRetrievalService(
            self.archive_search,
            self.archive_semantic_search,
        )
        self.source_context_builder = SourceContextBuilderService(
            self.source_anchors
        )
        self.source_grounded_chat = SourceGroundedChatService(
            chat_generation=self.chat_generation,
            embedding_provider=self.embedding_provider,
            archive_retrieval=self.archive_hybrid_retrieval,
            context_builder=self.source_context_builder,
            context_packages=self.context_packages,
            model_runs=self.model_runs,
        )
        self.source_analysis_repository = SourceAnalysisRepository(self.database)
        self.source_analysis_service = SourceAnalysisService(
            jobs=self.jobs,
            repository=self.source_analysis_repository,
            source_text=self.source_text,
            source_chunks=self.source_chunks,
            source_anchors=self.source_anchors,
            provider=self.model_provider,
            runs=self.model_runs,
            chat=self.chat,
            context_packages=self.context_packages,
        )
        self.source_analysis = DurableSourceAnalysisWorker(
            jobs=self.jobs,
            service=self.source_analysis_service,
        )
        self.research = ResearchService(
            repository=self.research_repository,
            jobs=self.jobs,
            source_analysis=self.source_analysis_service,
        )
        self.external_research = ExternalResearchService(
            gateway=self.external_access,
            research=self.research,
        )
        self.research_promotion = ResearchPromotionService(
            database=self.database,
            chat=self.chat,
            research=self.research_repository,
            source_analyses=self.source_analysis_repository,
            anchors=self.source_anchors,
        )
        self.research_synthesis = ResearchSynthesisService(
            repository=self.research_repository,
            source_analysis=self.source_analysis_service,
        )
        self.source_processing = DurableSourceProcessingWorker(
            jobs=self.jobs,
            sources=self.sources,
            source_text=self.source_text,
            source_pdf=self.source_pdf,
            source_docx=self.source_docx,
            source_html=self.source_html,
            source_chunks=self.source_chunks,
        )
        self.research_worker = DurableResearchWorker(
            jobs=self.jobs,
            service=self.research,
            source_processing=self.source_processing,
            synthesis=self.research_synthesis,
        )
        self.embedding_rebuild = DurableEmbeddingRebuildWorker(
            jobs=self.jobs,
            semantic=self.archive_semantic_search,
        )
        self.reviews = ReviewService(self.database)
        self.source_extraction_snapshots = SourceExtractionSnapshotRepository(
            self.database, self.model_runs
        )
        self.source_extraction = SourceAnalysisKnowledgeExtractionService(
            repository=self.source_analysis_repository,
            anchors=self.source_anchors,
            chat=self.chat,
            chat_generation=self.chat_generation,
            provider=self.model_provider,
            runs=self.model_runs,
            snapshots=self.source_extraction_snapshots,
        )
        self.source_hierarchical_extraction_repository = SourceHierarchicalExtractionRepository(
            self.database
        )
        self.source_hierarchical_extraction_service = SourceHierarchicalExtractionService(
            jobs=self.jobs,
            repository=self.source_hierarchical_extraction_repository,
            analyses=self.source_analysis_repository,
            anchors=self.source_anchors,
            base_extraction=self.source_extraction,
            provider=self.model_provider,
            runs=self.model_runs,
            snapshots=self.source_extraction_snapshots,
            context_packages=self.context_packages,
        )
        self.source_hierarchical_extraction = DurableSourceHierarchicalExtractionWorker(
            jobs=self.jobs,
            service=self.source_hierarchical_extraction_service,
        )
        self.news = NewsService(self)
        self.job_scheduler = DurableJobScheduler(
            jobs=self.jobs,
            source_worker=self.source_processing,
            embedding_worker=self.embedding_rebuild,
            analysis_worker=self.source_analysis,
            extraction_worker=self.source_hierarchical_extraction,
            research_worker=self.research_worker,
            resources=self.resources,
            news_worker=self.news,
        )
        self.source_proposal_acceptance = SourceProposalAcceptanceService(
            database=self.database,
            chat=self.chat,
            analyses=self.source_analysis_repository,
            anchors=self.source_anchors,
            reviews=self.reviews,
            snapshots=self.source_extraction_snapshots,
        )
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
            hnsw_root=self.paths.derived_root / "hnsw",
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
            context_packages=self.context_packages,
            evidence_policy=self.memory_evidence_policy,
            personal_memory=self.personal_memory,
            model_runs=self.model_runs,
        )
        self.unified_local_chat = UnifiedLocalChatService(
            chat_generation=self.chat_generation,
            embedding_provider=self.embedding_provider,
            hybrid_retrieval=self.hybrid_retrieval,
            memory_context_builder=self.context_builder,
            evidence_policy=self.memory_evidence_policy,
            personal_memory=self.personal_memory,
            archive_retrieval=self.archive_hybrid_retrieval,
            source_context_builder=self.source_context_builder,
            context_packages=self.context_packages,
            model_runs=self.model_runs,
        )
        self.adaptive_retrieval_planner = AdaptiveRetrievalPlanner(
            local_search=self.search,
            archive_search=self.archive_search,
            prior_research=self.prior_research_search,
            news_events=self.news_event_search,
        )
        self.adaptive_chat = AdaptiveChatService(
            chat=self.chat,
            planner=self.adaptive_retrieval_planner,
            direct_chat=self.direct_chat,
            memory_chat=self.memory_chat,
            source_grounded_chat=self.source_grounded_chat,
            unified_local_chat=self.unified_local_chat,
            research_grounded_chat=self.research_grounded_chat,
            news_grounded_chat=self.news_grounded_chat,
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
            self.news.start()
            recovered_backups = self.backup.recover_incomplete()
            if recovered_backups:
                logger.warning(
                    "Recovered interrupted backup publication",
                    extra={
                        "event": "backup.startup_recovered",
                        "recovered_backup_count": len(recovered_backups),
                    },
                )
            recovered_jobs = self.jobs.recover_startup()
            if recovered_jobs:
                logger.warning(
                    "Recovered expired durable job leases",
                    extra={
                        "event": "jobs.startup_recovered",
                        "recovered_job_count": len(recovered_jobs),
                    },
                )
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
