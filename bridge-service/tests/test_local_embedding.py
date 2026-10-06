"""Local embedding cache behavior tests."""

from unittest.mock import MagicMock

import pytest

from src.services import local_embedding


@pytest.mark.asyncio
async def test_model_cache_directory_is_forwarded_during_warmup(monkeypatch, tmp_path):
    model = MagicMock()
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(local_embedding, "TextEmbedding", factory)

    embedding = local_embedding.LocalEmbedding(
        model_name="example/model",
        cache_dir=str(tmp_path),
    )
    await embedding.warmup()

    factory.assert_called_once_with(
        model_name="example/model",
        cache_dir=str(tmp_path),
    )
    assert embedding._model is model
