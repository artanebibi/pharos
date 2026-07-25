from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical", "unknown"]

UNKNOWN_FAILURE_MODE = "unknown_failure_mode"

class IncidentContext(BaseModel):
    pod_name: str
    namespace: str
    logs: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    chunk_id: str
    document: str
    metadata: dict
    similarity: float


class Diagnosis(BaseModel):
    root_cause: str
    retrieval_relevance_score: float
    severity: Severity
    remediation_steps: list[str]
    kubectl_commands: list[str]
    sources_used: list[str]
    reasoning: str
