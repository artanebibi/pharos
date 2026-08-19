from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    embedder_backend: str
    retriever_backend: str
    reasoner_backend: str
    incident_store_backend: str

    embedding_model: str

    chroma_host: str
    chroma_port: int
    collection_name: str

    gcp_project: str | None
    vertex_location: str
    vertex_embedding_model: str
    vertex_embedding_dim: int

    firestore_database: str
    firestore_collection: str

    gemini_api_key: str | None
    gemini_model: str

    top_k: int
    ood_floor_threshold: float
    max_log_chars: int

    runbooks_dir: Path
    diagnose_log_path: Path


def load_settings() -> Settings:
    return Settings(
        embedder_backend=os.getenv("EMBEDDER_BACKEND", "local"),
        retriever_backend=os.getenv("RETRIEVER_BACKEND", "chroma_local"),
        reasoner_backend=os.getenv("REASONER_BACKEND", "gemini"),
        incident_store_backend=os.getenv("INCIDENT_STORE_BACKEND", "sqlite"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        collection_name=os.getenv("CHROMA_COLLECTION", "pharos_corpus"),
        gcp_project=os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT"),
        vertex_location=os.getenv("VERTEX_LOCATION", "europe-west3"),
        vertex_embedding_model=os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-005"),
        vertex_embedding_dim=int(os.getenv("VERTEX_EMBEDDING_DIM", "768")),
        firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        firestore_collection=os.getenv("FIRESTORE_COLLECTION", "pharos_corpus"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        top_k=int(os.getenv("TOP_K", "5")),
        ood_floor_threshold=float(os.getenv("OOD_FLOOR_THRESHOLD", "0.3")),
        max_log_chars=int(os.getenv("MAX_LOG_CHARS", "4000")),
        runbooks_dir=Path(os.getenv("RUNBOOKS_DIR", str(REPO_ROOT / "runbooks"))),
        diagnose_log_path=Path(
            os.getenv("DIAGNOSE_LOG_PATH", str(REPO_ROOT / "tests" / "logs" / "diagnose_log.jsonl"))
        ),
    )


settings = load_settings()
