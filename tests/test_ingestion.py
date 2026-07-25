import pytest

from ingestion import (
    EXPECTED_SECTIONS,
    chunk_runbook,
    format_incident_memory_document,
    ingest_incident_memory,
)

SAMPLE_RUNBOOK = """# CrashLoopBackOff

## Symptom
Pod status shows `CrashLoopBackOff` and the RESTARTS count climbs.

## Root Causes
1. Missing required environment variable or secret.
2. Bad entrypoint command.

## Diagnosis Steps
1. `kubectl logs <pod> --previous`
2. `kubectl describe pod <pod>` and read the exit code.

## Remediation
1. Create the missing ConfigMap, then `kubectl rollout restart deployment/<name>`.
"""


def test_chunks_one_per_h2_section():
    chunks = chunk_runbook(SAMPLE_RUNBOOK, "crashloop-backoff.md")
    assert len(chunks) == 4


def test_section_metadata_is_correct_and_ordered():
    chunks = chunk_runbook(SAMPLE_RUNBOOK, "crashloop-backoff.md")
    assert [c.metadata["section"] for c in chunks] == EXPECTED_SECTIONS
    assert all(c.metadata["source"] == "runbook" for c in chunks)
    assert all(c.metadata["runbook_file"] == "crashloop-backoff.md" for c in chunks)


def test_h1_title_is_prepended_to_every_chunk():
    chunks = chunk_runbook(SAMPLE_RUNBOOK, "crashloop-backoff.md")
    for chunk in chunks:
        assert chunk.document.startswith("CrashLoopBackOff — ")
        assert chunk.metadata["section"] in chunk.document.splitlines()[0]


def test_chunk_ids_are_deterministic():
    first = chunk_runbook(SAMPLE_RUNBOOK, "crashloop-backoff.md")
    second = chunk_runbook(SAMPLE_RUNBOOK, "crashloop-backoff.md")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert first[0].chunk_id == "crashloop-backoff.md::Symptom"


def test_section_bodies_do_not_bleed_into_each_other():
    chunks = {c.metadata["section"]: c.document for c in chunk_runbook(SAMPLE_RUNBOOK, "x.md")}
    assert "Missing required environment variable" in chunks["Root Causes"]
    assert "Missing required environment variable" not in chunks["Symptom"]
    assert "rollout restart" in chunks["Remediation"]
    assert "rollout restart" not in chunks["Diagnosis Steps"]


def test_runbook_without_h1_fails_loudly():
    with pytest.raises(ValueError, match="no H1 title"):
        chunk_runbook("## Symptom\nno title here\n", "broken.md")


class _FakeEmbedder:
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class _RecordingRetriever:
    def __init__(self):
        self.upserts = []

    def query(self, query_embedding, top_k=5):
        return []

    def upsert(self, chunk_id, embedding, document, metadata):
        self.upserts.append(
            {"chunk_id": chunk_id, "embedding": embedding,
             "document": document, "metadata": metadata}
        )


INCIDENT = {
    "pod_name": "crashloop-demo-abc12",
    "namespace": "workloads",
    "logs": ["Simulated crash: missing config"],
    "metrics": {"restart_count": 6},
    "events": ["Back-off restarting failed container"],
}

DIAGNOSIS = {
    "root_cause": "missing configuration causes container to exit 1",
    "retrieval_relevance_score": 0.82,
    "severity": "high",
    "remediation_steps": ["Create the missing ConfigMap", "Restart the deployment"],
    "kubectl_commands": ["kubectl rollout restart deployment/crashloop-demo -n workloads"],
    "sources_used": ["crashloop-backoff.md::Root Causes"],
    "reasoning": "Exit code 1 plus the log line points at missing config.",
}


def test_incident_memory_document_carries_the_evidence_and_the_fix():
    document = format_incident_memory_document(INCIDENT, DIAGNOSIS)
    assert "missing configuration causes container to exit 1" in document
    assert "crashloop-demo-abc12" in document
    assert "Simulated crash: missing config" in document
    assert "Create the missing ConfigMap" in document
    assert "kubectl rollout restart deployment/crashloop-demo -n workloads" in document


def test_incident_memory_is_upserted_with_source_metadata():
    retriever = _RecordingRetriever()
    ingest_incident_memory(INCIDENT, DIAGNOSIS, embedder=_FakeEmbedder(), retriever=retriever)

    assert len(retriever.upserts) == 1
    upsert = retriever.upserts[0]
    assert upsert["metadata"]["source"] == "incident_memory"
    assert "ingested_at" in upsert["metadata"]
    assert upsert["chunk_id"] == "incident::workloads/crashloop-demo-abc12"
    assert upsert["embedding"] == [0.1, 0.2, 0.3]


def test_re_ingesting_the_same_pod_reuses_the_id():
    retriever = _RecordingRetriever()
    ingest_incident_memory(INCIDENT, DIAGNOSIS, embedder=_FakeEmbedder(), retriever=retriever)
    ingest_incident_memory(INCIDENT, DIAGNOSIS, embedder=_FakeEmbedder(), retriever=retriever)
    assert len({u["chunk_id"] for u in retriever.upserts}) == 1
