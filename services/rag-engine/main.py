from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from config import settings
from embedder import build_embedder
from prompts import SCHEMA_RETRY_INSTRUCTION, build_diagnosis_prompt
from reasoner import build_reasoner
from retriever import build_retriever
from schemas import UNKNOWN_FAILURE_MODE, Diagnosis, IncidentContext, RetrievedChunk

components: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    components["embedder"] = build_embedder(settings)
    components["retriever"] = build_retriever(settings)
    components["reasoner"] = build_reasoner(settings)
    settings.diagnose_log_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"[rag-engine] embedder={settings.embedder_backend} "
        f"retriever={settings.retriever_backend} reasoner={settings.reasoner_backend} "
        f"ood_floor={settings.ood_floor_threshold}"
    )
    yield
    components.clear()


app = FastAPI(title="rag-engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rag-engine"}

QUERY_LOG_CHARS = 1000


def build_query_string(incident: IncidentContext) -> str:
    parts: list[str] = []
    if incident.logs:
        parts.append(" ".join(incident.logs)[:QUERY_LOG_CHARS])
    if incident.events:
        parts.extend(incident.events[:3])
    if incident.metrics:
        parts.append(", ".join(f"{k}={v}" for k, v in sorted(incident.metrics.items())))
    return ". ".join(parts) if parts else "no telemetry evidence available"


def _strip_code_fences(text: str) -> str:
    fenced = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    return fenced.group(1) if fenced else text.strip()


def parse_diagnosis(raw: str) -> Diagnosis:
    return Diagnosis.model_validate(json.loads(_strip_code_fences(raw)))


def log_record(
    incident: IncidentContext,
    prompt: str | None,
    raw_response: str | None,
    diagnosis: Diagnosis | None,
    ood_escalated: bool,
    schema_failure: bool = False,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "incident_context": incident.model_dump(),
        "ood_escalated": ood_escalated,
        "schema_failure": schema_failure,
        "prompt": prompt,
        "raw_response": raw_response,
        "diagnosis": diagnosis.model_dump() if diagnosis else None,
    }
    settings.diagnose_log_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.diagnose_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def escalate_out_of_distribution(
    max_similarity: float, threshold: float, chunk_count: int
) -> Diagnosis:
    return Diagnosis(
        root_cause=UNKNOWN_FAILURE_MODE,
        retrieval_relevance_score=max_similarity,
        severity="unknown",
        remediation_steps=[],
        kubectl_commands=[],
        sources_used=[],
        reasoning=(
            f"Out-of-distribution: best retrieval-relevance score across "
            f"{chunk_count} retrieved chunks was {max_similarity:.3f}, below the "
            f"floor of {threshold:.3f}. This incident does not sufficiently match "
            f"any known pattern in the corpus, so no diagnosis was generated. "
            f"Escalating to a human."
        ),
    )


@app.post("/diagnose", response_model=Diagnosis)
def diagnose(incident: IncidentContext) -> Diagnosis:
    embedder = components["embedder"]
    retriever = components["retriever"]
    reasoner = components["reasoner"]

    query = build_query_string(incident)
    chunks: list[RetrievedChunk] = retriever.query(
        embedder.embed_query(query), top_k=settings.top_k
    )

    max_similarity = max((c.similarity for c in chunks), default=0.0)

    if max_similarity < settings.ood_floor_threshold:
        diagnosis = escalate_out_of_distribution(
            max_similarity, settings.ood_floor_threshold, len(chunks)
        )
        log_record(incident, prompt=None, raw_response=None, diagnosis=diagnosis,
                   ood_escalated=True)
        return diagnosis

    prompt = build_diagnosis_prompt(
        incident=incident,
        chunks=chunks,
        retrieval_relevance_score=max_similarity,
        max_log_chars=settings.max_log_chars,
    )

    raw_response = reasoner.generate(prompt)
    try:
        diagnosis = parse_diagnosis(raw_response)
    except (json.JSONDecodeError, ValidationError) as first_error:
        retry_prompt = prompt + SCHEMA_RETRY_INSTRUCTION
        retry_response = reasoner.generate(retry_prompt)
        try:
            diagnosis = parse_diagnosis(retry_response)
        except (json.JSONDecodeError, ValidationError) as second_error:
            log_record(
                incident,
                prompt=retry_prompt,
                raw_response=retry_response,
                diagnosis=None,
                ood_escalated=False,
                schema_failure=True,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "LLM output failed Diagnosis schema validation twice",
                    "first_error": str(first_error),
                    "second_error": str(second_error),
                    "last_raw_response": retry_response[:2000],
                },
            ) from second_error
        prompt, raw_response = retry_prompt, retry_response

    diagnosis.retrieval_relevance_score = max_similarity

    log_record(incident, prompt=prompt, raw_response=raw_response, diagnosis=diagnosis,
               ood_escalated=False)
    return diagnosis