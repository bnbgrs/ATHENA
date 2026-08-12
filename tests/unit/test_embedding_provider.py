from __future__ import annotations

import json

from athena.model.adapters.lm_studio import LMStudioProvider
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def test_embedding_provider_preserves_input_order(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }
        )

    monkeypatch.setattr(
        "athena.model.adapters.lm_studio_embeddings.urlopen",
        fake_urlopen,
    )
    provider = LMStudioEmbeddingProvider(
        LMStudioProvider(base_url="http://127.0.0.1:1234")
    )
    assert provider.embed(
        model_id="embed",
        texts=["first", "second"],
    ) == ((1.0, 0.0), (0.0, 1.0))
