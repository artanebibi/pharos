import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import main
from schemas import RetrievedChunk

INCIDENT_PAYLOAD = {
    "pod_name": "crashy",
    "namespace": "workloads",
    "logs": ["Simulated crash: missing config"],
    "metrics": {"restart_count": 3},
    "events": ["Back-off restarting failed container"],
}

GOOD_RESPONSE = json.dumps(
    {
        "root_cause": "missing config",
        "retrieval_relevance_score": 0.9,
        "severity": "high",
        "remediation_steps": ["fix it"],
        "kubectl_commands": ["kubectl get pods -n workloads"],
        "sources_used": ["crashloop-backoff.md::Symptom"],
        "reasoning": "because",
    }
)


class StubEmbedder:
    def embed_query(self, text):
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


class StubRetriever:
    def __init__(self, similarities):
        self.similarities = similarities

    def query(self, query_embedding, top_k=5):
        return [
            RetrievedChunk(
                chunk_id=f"runbook-{i}.md::Symptom",
                document="doc",
                metadata={"source": "runbook"},
                similarity=s,
            )
            for i, s in enumerate(self.similarities)
        ]

    def upsert(self, chunk_id, embedding, document, metadata):
        raise AssertionError("upsert must not be called during /diagnose")


class StubReasoner:
    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main, "settings",
        dataclasses.replace(main.settings, diagnose_log_path=tmp_path / "diagnose_log.jsonl"),
    )
    monkeypatch.setitem(main.components, "embedder", StubEmbedder())
    return TestClient(main.app)


def test_normal_path_returns_incident_id_and_pending_review_row(client, monkeypatch):
    monkeypatch.setitem(main.components, "retriever", StubRetriever([0.9, 0.5]))
    monkeypatch.setitem(main.components, "reasoner", StubReasoner(response=GOOD_RESPONSE))

    resp = client.post("/diagnose", json=INCIDENT_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"]

    record = main.components["incident_store"].get(body["incident_id"])
    assert record is not None
    assert record.status == "PENDING_REVIEW"


def test_ood_path_also_returns_incident_id_and_pending_review_row(client, monkeypatch):
    monkeypatch.setitem(main.components, "retriever", StubRetriever([0.1, 0.05]))
    monkeypatch.setitem(main.components, "reasoner", StubReasoner(response="unused"))

    resp = client.post("/diagnose", json=INCIDENT_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_id"]
    assert body["root_cause"] == "unknown_failure_mode"

    record = main.components["incident_store"].get(body["incident_id"])
    assert record is not None
    assert record.status == "PENDING_REVIEW"


def test_generation_failure_returns_502_and_creates_no_incident_row(client, monkeypatch):
    monkeypatch.setitem(main.components, "retriever", StubRetriever([0.9, 0.5]))
    monkeypatch.setitem(
        main.components, "reasoner",
        StubReasoner(raise_exc=RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")),
    )

    resp = client.post("/diagnose", json=INCIDENT_PAYLOAD)

    assert resp.status_code == 502

    log_lines = main.settings.diagnose_log_path.read_text().strip().splitlines()
    last_record = json.loads(log_lines[-1])
    assert "quota exceeded" in last_record["generation_failure"]

    assert main.components["incident_store"].list_by_status("PENDING_REVIEW") == []
