import pytest
from fastapi.testclient import TestClient

import main
from schemas import Diagnosis, IncidentContext


def make_context():
    return IncidentContext(pod_name="p1", namespace="workloads", logs=[], metrics={}, events=[])


def make_diagnosis():
    return Diagnosis(
        root_cause="missing config",
        retrieval_relevance_score=0.9,
        severity="high",
        remediation_steps=[],
        kubectl_commands=[],
        sources_used=[],
        reasoning="r",
    )


class CountingRetriever:
    def __init__(self, start):
        self.n = start

    def count(self):
        return self.n


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(main.components, "embedder", object())
    monkeypatch.setitem(main.components, "retriever", CountingRetriever(start=12))
    return TestClient(main.app)


@pytest.fixture
def store():
    return main.components["incident_store"]


def _mock_ingest(monkeypatch):
    calls = []

    def fake_ingest(context, diagnosis, **kwargs):
        calls.append((context, diagnosis))
        main.components["retriever"].n += 1

    monkeypatch.setattr(main, "ingest_incident_memory", fake_ingest)
    return calls


def test_memorize_before_approve_returns_409(client, store):
    incident_id = store.create(make_context(), make_diagnosis(), 0.9)

    resp = client.post(f"/incidents/{incident_id}/memorize")

    assert resp.status_code == 409


def test_approve_then_memorize_increments_corpus_size(client, store, monkeypatch):
    calls = _mock_ingest(monkeypatch)
    incident_id = store.create(make_context(), make_diagnosis(), 0.9)

    approve_resp = client.post(f"/incidents/{incident_id}/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED"

    resp = client.post(f"/incidents/{incident_id}/memorize")

    assert resp.status_code == 200
    body = resp.json()
    assert body["corpus_size"] == 13
    assert len(calls) == 1
    assert store.get(incident_id).status == "MEMORIZED"


def test_memorize_twice_is_idempotent_and_does_not_re_ingest(client, store, monkeypatch):
    calls = _mock_ingest(monkeypatch)
    incident_id = store.create(make_context(), make_diagnosis(), 0.9)
    client.post(f"/incidents/{incident_id}/approve")

    first = client.post(f"/incidents/{incident_id}/memorize")
    assert first.status_code == 200
    assert len(calls) == 1

    second = client.post(f"/incidents/{incident_id}/memorize")

    assert second.status_code == 200
    body = second.json()
    assert body["already_memorized"] is True
    assert body["corpus_size"] == 13
    assert len(calls) == 1
