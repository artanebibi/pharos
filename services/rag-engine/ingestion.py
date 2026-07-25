from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import Settings, settings as default_settings
from embedder import Embedder, build_embedder
from retriever import Retriever, build_retriever

EXPECTED_SECTIONS = ["Symptom", "Root Causes", "Diagnosis Steps", "Remediation"]

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document: str
    metadata: dict


def chunk_runbook(text: str, runbook_file: str) -> list[Chunk]:
    h1_match = _H1_RE.search(text)
    if not h1_match:
        raise ValueError(f"{runbook_file}: no H1 title found")
    title = h1_match.group(1).strip()

    parts = _H2_SPLIT_RE.split(text)
    sections = list(zip(parts[1::2], parts[2::2]))
    if not sections:
        raise ValueError(f"{runbook_file}: no '## Section' headings found")

    chunks: list[Chunk] = []
    for section_name, body in sections:
        section_name = section_name.strip()
        chunks.append(
            Chunk(
                chunk_id=f"{runbook_file}::{section_name}",
                document=f"{title} — {section_name}\n\n{body.strip()}",
                metadata={
                    "source": "runbook",
                    "runbook_file": runbook_file,
                    "section": section_name,
                },
            )
        )
    return chunks


def seed_runbooks(
    runbooks_dir: Path | None = None,
    embedder: Embedder | None = None,
    retriever: Retriever | None = None,
    settings: Settings = default_settings,
) -> int:
    runbooks_dir = runbooks_dir or settings.runbooks_dir
    embedder = embedder or build_embedder(settings)
    retriever = retriever or build_retriever(settings)

    runbook_paths = sorted(runbooks_dir.glob("*.md"))
    if not runbook_paths:
        raise FileNotFoundError(f"No runbooks found in {runbooks_dir}")

    all_chunks: list[Chunk] = []
    for path in runbook_paths:
        chunks = chunk_runbook(path.read_text(encoding="utf-8"), path.name)
        found = [c.metadata["section"] for c in chunks]
        if found != EXPECTED_SECTIONS:
            print(f"  ! {path.name}: sections {found} != expected {EXPECTED_SECTIONS}")
        all_chunks.extend(chunks)
        print(f"  + {path.name}: {len(chunks)} chunks ({', '.join(found)})")

    embeddings = embedder.embed_documents([c.document for c in all_chunks])
    for chunk, embedding in zip(all_chunks, embeddings):
        retriever.upsert(
            chunk_id=chunk.chunk_id,
            embedding=embedding,
            document=chunk.document,
            metadata=chunk.metadata,
        )

    return len(all_chunks)


def format_incident_memory_document(incident_context: dict, diagnosis: dict) -> str:
    logs = "\n".join(incident_context.get("logs", []) or [])
    events = "\n".join(f"- {e}" for e in incident_context.get("events", []) or [])
    steps = "\n".join(
        f"{i}. {s}" for i, s in enumerate(diagnosis.get("remediation_steps", []) or [], 1)
    )
    commands = "\n".join(f"- `{c}`" for c in diagnosis.get("kubectl_commands", []) or [])

    return f"""# Resolved Incident — {diagnosis.get("root_cause", "unknown")}

## Symptom
Pod `{incident_context.get("pod_name")}` in namespace `{incident_context.get("namespace")}`.
Metrics: {incident_context.get("metrics", {})}

Events:
{events or "(none)"}

Logs:
{logs or "(none)"}

## Root Causes
{diagnosis.get("root_cause", "unknown")} (severity: {diagnosis.get("severity", "unknown")})

## Diagnosis Steps
{diagnosis.get("reasoning", "")}

## Remediation
{steps or "(none recorded)"}

{commands}
"""


def ingest_incident_memory(
    incident_context: dict,
    diagnosis: dict,
    embedder: Embedder | None = None,
    retriever: Retriever | None = None,
    settings: Settings = default_settings,
) -> None:
    embedder = embedder or build_embedder(settings)
    retriever = retriever or build_retriever(settings)

    ingested_at = datetime.now(timezone.utc).isoformat()
    document = format_incident_memory_document(incident_context, diagnosis)
    chunk_id = f"incident::{incident_context.get('namespace')}/{incident_context.get('pod_name')}"

    retriever.upsert(
        chunk_id=chunk_id,
        embedding=embedder.embed_query(document),
        document=document,
        metadata={"source": "incident_memory", "ingested_at": ingested_at},
    )
