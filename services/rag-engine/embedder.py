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


class VertexEmbedder(Embedder):

    MAX_BATCH = 32

    def __init__(
        self,
        project: str | None = None,
        location: str = "europe-west3",
        model_name: str = "text-embedding-005",
        dimensionality: int = 768,
    ) -> None:
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        self.model_name = model_name
        self.dimensionality = dimensionality

        vertexai.init(project=project, location=location)
        self._model = TextEmbeddingModel.from_pretrained(model_name)

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from vertexai.language_models import TextEmbeddingInput

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.MAX_BATCH):
            batch = texts[start : start + self.MAX_BATCH]
            inputs = [TextEmbeddingInput(text, task_type) for text in batch]
            predictions = self._model.get_embeddings(
                inputs, output_dimensionality=self.dimensionality
            )
            vectors.extend(list(p.values) for p in predictions)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder_backend == "local":
        return LocalEmbedder(settings.embedding_model)
    if settings.embedder_backend == "vertex":
        return VertexEmbedder(
            project=settings.gcp_project,
            location=settings.vertex_location,
            model_name=settings.vertex_embedding_model,
            dimensionality=settings.vertex_embedding_dim,
        )
    raise ValueError(
        f"Unknown EMBEDDER_BACKEND={settings.embedder_backend!r} "
        f"(expected 'local' or 'vertex')"
    )
