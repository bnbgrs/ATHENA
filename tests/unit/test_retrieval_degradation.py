from __future__ import annotations

from dataclasses import dataclass

import pytest

from athena.model.adapters.lm_studio import ModelProviderError
from athena.model.domain import ModelInfo
from athena.retrieval.degradation import (
    EMBEDDING_MODEL_NOT_LOADED_WARNING,
    EMBEDDING_MODEL_UNAVAILABLE_WARNING,
    HYBRID_RETRIEVAL_MODE,
    LEXICAL_FALLBACK_RETRIEVAL_MODE,
    resolve_embedding_model_for_retrieval,
)


def _model(
    *,
    loaded: bool,
) -> ModelInfo:
    return ModelInfo(
        provider="lm_studio",
        backend_model_id="embed-model",
        display_name="Embed Model",
        model_type="embedding",
        context_capacity=2048,
        quantization="Q4_K_M",
        loaded=loaded,
        vision=False,
        trained_for_tool_use=False,
    )


@dataclass
class FakeProvider:
    model: ModelInfo | None = None
    fail: bool = False

    def resolve_model(
        self,
        requested_model_id: str | None = None,
    ) -> ModelInfo:
        assert (
            requested_model_id
            == "embed-model"
        )

        if self.fail:
            raise ModelProviderError(
                "synthetic unavailable"
            )

        assert self.model is not None

        return self.model


def test_loaded_embedding_model_keeps_hybrid_mode() -> None:
    resolution = (
        resolve_embedding_model_for_retrieval(
            FakeProvider(
                model=_model(
                    loaded=True
                )
            ),  # type: ignore[arg-type]
            "embed-model",
        )
    )

    assert (
        resolution.mode
        == HYBRID_RETRIEVAL_MODE
    )
    assert (
        resolution.model
        is not None
    )
    assert (
        resolution.model.loaded
        is True
    )
    assert (
        resolution.warning
        is None
    )


def test_unloaded_embedding_model_degrades_without_embedding_call() -> None:
    resolution = (
        resolve_embedding_model_for_retrieval(
            FakeProvider(
                model=_model(
                    loaded=False
                )
            ),  # type: ignore[arg-type]
            "embed-model",
        )
    )

    assert (
        resolution.mode
        == LEXICAL_FALLBACK_RETRIEVAL_MODE
    )
    assert (
        resolution.model
        is None
    )
    assert (
        resolution.warning
        == EMBEDDING_MODEL_NOT_LOADED_WARNING
    )


def test_unavailable_embedding_model_degrades_to_lexical() -> None:
    resolution = (
        resolve_embedding_model_for_retrieval(
            FakeProvider(
                fail=True
            ),  # type: ignore[arg-type]
            "embed-model",
        )
    )

    assert (
        resolution.mode
        == LEXICAL_FALLBACK_RETRIEVAL_MODE
    )
    assert (
        resolution.model
        is None
    )
    assert (
        resolution.warning
        == EMBEDDING_MODEL_UNAVAILABLE_WARNING
    )


def test_blank_explicit_embedding_model_id_remains_invalid() -> None:
    with pytest.raises(
        ValueError,
        match="must not be empty",
    ):
        resolve_embedding_model_for_retrieval(
            FakeProvider(
                model=_model(
                    loaded=True
                )
            ),  # type: ignore[arg-type]
            "   ",
        )
