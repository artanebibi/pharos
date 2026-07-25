from __future__ import annotations

from abc import ABC, abstractmethod

from config import Settings
from schemas import RetrievedChunk


class Retriever(ABC):
    @abstractmethod
    def query(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        ...

    @abstractmethod
    def upsert(
        self, chunk_id: str, embedding: list[float], document: str, metadata: dict
    ) -> None:
        ...


class ChromaRetriever(Retriever):
    def __init__(self, host: str, port: int, collection_name: str) -> None:
        import chromadb

        self._client = chromadb.HttpClient(host=host, port=port)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def query(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        chunks: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document=document,
                    metadata=dict(metadata or {}),
                    similarity=1.0 - float(distance),
                )
            )
        return chunks

    def upsert(
        self, chunk_id: str, embedding: list[float], document: str, metadata: dict
    ) -> None:
        self._collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[document],
            metadatas=[metadata],
        )

    def count(self) -> int:
        return self._collection.count()


def build_retriever(settings: Settings) -> Retriever:
    if settings.retriever_backend == "chroma_local":
        return ChromaRetriever(
            host=settings.chroma_host,
            port=settings.chroma_port,
            collection_name=settings.collection_name,
        )
    raise ValueError(
        f"Unknown RETRIEVER_BACKEND={settings.retriever_backend!r} (expected 'chroma_local')"
    )
