from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "rag-engine"))

from config import settings  # noqa: E402
from ingestion import seed_runbooks  # noqa: E402


def main() -> int:
    print(f"[indexer] runbooks: {settings.runbooks_dir}")
    print(
        f"[indexer] target: chroma://{settings.chroma_host}:{settings.chroma_port}"
        f"/{settings.collection_name}"
    )
    print(f"[indexer] embedder: {settings.embedder_backend} ({settings.embedding_model})")

    try:
        count = seed_runbooks(settings=settings)
    except Exception as exc:
        print(f"[indexer] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"[indexer] indexed {count} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
