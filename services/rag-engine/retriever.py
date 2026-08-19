from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import quote

from config import Settings
from schemas import RetrievedChunk


class Retriever(ABC):
    backend_name: str = "unknown"
    performs_retrieval: bool = True

    @abstractmethod
    def query(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        ...

    @abstractmethod
    def upsert(
        self, chunk_id: str, embedding: list[float], document: str, metadata: dict
    ) -> None:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


class NoRetriever(Retriever):

    backend_name = "none"
    performs_retrieval = False

    def query(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        return []

    def upsert(
        self, chunk_id: str, embedding: list[float], document: str, metadata: dict
    ) -> None:
        return None

    def count(self) -> int:
        return 0


class ChromaRetriever(Retriever):
    backend_name = "chroma_local"

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

DISTANCE_FIELD = "vector_distance"
RESERVED_FIELDS = frozenset({"id", "embedding", "document", DISTANCE_FIELD})


def firestore_document_id(chunk_id: str) -> str:
    return quote(chunk_id, safe=":.-_=+")


class FirestoreRetriever(Retriever):
    backend_name = "firestore"

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        collection_name: str = "pharos_corpus",
    ) -> None:
        from google.cloud import firestore

        self.collection_name = collection_name
        self._client = firestore.Client(project=project, database=database)
        self._collection = self._client.collection(collection_name)

    def query(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        snapshots = self._collection.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=top_k,
            distance_result_field=DISTANCE_FIELD,
        ).get()

        chunks: list[RetrievedChunk] = []
        for snapshot in snapshots:
            data = snapshot.to_dict() or {}
            distance = float(data.get(DISTANCE_FIELD, 1.0))
            chunks.append(
                RetrievedChunk(
                    chunk_id=data.get("id") or snapshot.id,
                    document=data.get("document", ""),
                    metadata={k: v for k, v in data.items() if k not in RESERVED_FIELDS},
                    similarity=1.0 - distance,
                )
            )
        return chunks

    def upsert(
        self, chunk_id: str, embedding: list[float], document: str, metadata: dict
    ) -> None:
        from google.cloud.firestore_v1.vector import Vector

        payload = dict(metadata or {})
        payload.update(
            {
                "id": chunk_id,
                "document": document,
                "embedding": Vector(embedding),
            }
        )
        self._collection.document(firestore_document_id(chunk_id)).set(payload, merge=True)

    def count(self) -> int:
        result = self._collection.count().get()
        return int(result[0][0].value)


def build_retriever(settings: Settings) -> Retriever:
    if settings.retriever_backend == "chroma_local":
        return ChromaRetriever(
            host=settings.chroma_host,
            port=settings.chroma_port,
            collection_name=settings.collection_name,
        )
    if settings.retriever_backend == "firestore":
        return FirestoreRetriever(
            project=settings.gcp_project,
            database=settings.firestore_database,
            collection_name=settings.firestore_collection,
        )
    if settings.retriever_backend == "none":
        return NoRetriever()
    raise ValueError(
        f"Unknown RETRIEVER_BACKEND={settings.retriever_backend!r} "
        f"(expected 'chroma_local', 'firestore' or 'none')"
    )