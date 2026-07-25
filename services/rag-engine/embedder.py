from __future__ import annotations

from abc import ABC, abstractmethod

from config import Settings


class Embedder(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...


class LocalEmbedder(Embedder):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder_backend == "local":
        return LocalEmbedder(settings.embedding_model)
    raise ValueError(
        f"Unknown EMBEDDER_BACKEND={settings.embedder_backend!r} (expected 'local')"
    )
