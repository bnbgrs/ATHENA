"""Safe lexical degradation when semantic retrieval infrastructure is unavailable."""

from __future__ import annotations

from dataclasses import dataclass

from athena.model.adapters.lm_studio import ModelProviderError
from athena.model.adapters.lm_studio_embeddings import (
    LMStudioEmbeddingProvider,
)
from athena.model.domain import ModelInfo

HYBRID_RETRIEVAL_MODE = "hybrid"
LEXICAL_FALLBACK_RETRIEVAL_MODE = "lexical_fallback"

EMBEDDING_MODEL_UNAVAILABLE_WARNING = (
    "embedding_model_unavailable"
)
EMBEDDING_MODEL_NOT_LOADED_WARNING = (
    "embedding_model_not_loaded"
)


class SemanticRetrievalUnavailableError(
    RuntimeError
):
    """Raised only when semantic Derived State cannot be used."""

    def __init__(
        self,
        reason_code: str,
    ) -> None:
        normalized = (
            reason_code.strip()
        )

        if not normalized:
            raise ValueError(
                "Semantic retrieval fallback "
                "reason code must not be empty."
            )

        self.reason_code = normalized

        super().__init__(
            normalized
        )


@dataclass(
    frozen=True,
    slots=True,
)
class EmbeddingRetrievalResolution:
    """Resolved embedding infrastructure or explicit lexical fallback."""

    model: ModelInfo | None
    mode: str
    warning: str | None


def resolve_embedding_model_for_retrieval(
    provider: LMStudioEmbeddingProvider,
    requested_model_id: str | None,
) -> EmbeddingRetrievalResolution:
    """Resolve embeddings without making them a chat hard dependency."""

    if (
        requested_model_id
        is not None
        and not requested_model_id.strip()
    ):
        raise ValueError(
            "Embedding model id "
            "must not be empty."
        )

    try:
        model = provider.resolve_model(
            requested_model_id
        )
    except ModelProviderError:
        return EmbeddingRetrievalResolution(
            model=None,
            mode=(
                LEXICAL_FALLBACK_RETRIEVAL_MODE
            ),
            warning=(
                EMBEDDING_MODEL_UNAVAILABLE_WARNING
            ),
        )

    if not model.loaded:
        return EmbeddingRetrievalResolution(
            model=None,
            mode=(
                LEXICAL_FALLBACK_RETRIEVAL_MODE
            ),
            warning=(
                EMBEDDING_MODEL_NOT_LOADED_WARNING
            ),
        )

    return EmbeddingRetrievalResolution(
        model=model,
        mode=HYBRID_RETRIEVAL_MODE,
        warning=None,
    )
