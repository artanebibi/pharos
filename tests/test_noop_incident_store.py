import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import main
from incident_store import IncidentStore, NoopIncidentStore, build_incident_store
from schemas import Diagnosis, IncidentContext, RetrievedChunk

CONTEXT = IncidentContext(
    pod_name="checkout-api-7f9d",
    namespace="workloads",
    logs=["FATAL: DATABASE_URL environment variable not set", "exiting"],
    metrics={"restart_count": 6},
    events=["Back-off restarting failed container"],
)

DIAGNOSIS_JSON = {
    "root_cause": "DATABASE_URL is missing from the container environment",
    "retrieval_relevance_score": 0.81,
    "severity": "high",
    "remediation_steps": ["Add DATABASE_URL to the ConfigMap"],
    "kubectl_commands": ["kubectl rollout restart deployment/checkout-api -n workloads"],
    "sources_used": ["crashloop-backoff.md::Symptom"],
    "reasoning": "Grounded in the retrieved runbook.",
}


class StubEmbedder:
    def embed_documents(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]

    def embed_query(self, text):
        return [0.0, 0.0, 1.0]


class StubRetriever:
    backend_name = "firestore"
    performs_retrieval = True

    def query(self, query_embedding, top_k=5):
        return [
            RetrievedChunk(
                chunk_id="crashloop-backoff.md::Symptom",
                document="CrashLoopBackOff Symptom",
                metadata={"source": "runbook"},
                similarity=0.81,
            )
        ]

    def upsert(self, chunk_id, embedding, document, metadata):
        raise AssertionError("upsert must not be called during /diagnose")

    def count(self):
        return 60


class StubReasoner:
    def generate(self, prompt: str) -> str:
        return json.dumps(DIAGNOSIS_JSON)


def test_create_returns_a_uuid_and_persists_nothing(tmp_path, monkeypatch):
    db_path = tmp_path / "should-never-be-created.db"
    monkeypatch.setenv("INCIDENT_STORE_PATH", str(db_path))
    store = NoopIncidentStore()

    incident_id = store.create(CONTEXT, Diagnosis(**DIAGNOSIS_JSON), 0.81)

    assert isinstance(incident_id, str)
    assert len(incident_id) == 32
    int(incident_id, 16)
    assert not db_path.exists()


def test_each_create_returns_a_distinct_id():
    store = NoopIncidentStore()
    diagnosis = Diagnosis(**DIAGNOSIS_JSON)

    ids = {store.create(CONTEXT, diagnosis, 0.81) for _ in range(50)}

    assert len(ids) == 50


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.get("abc"),
        lambda s: s.update_status("abc", "APPROVED", {"PENDING_REVIEW"}),
        lambda s: s.list_by_status("PENDING_REVIEW"),
    ],
    ids=["get", "update_status", "list_by_status"],
)
def test_read_and_write_methods_raise_rather_than_lying(call):
    with pytest.raises(NotImplementedError, match="Phase 3"):
        call(NoopIncidentStore())


def test_it_matches_the_sqlite_store_interface():
    assert set(dir(NoopIncidentStore)) >= {
        name for name in dir(IncidentStore) if not name.startswith("_")
    }


def test_build_incident_store_selects_the_noop_backend():
    assert isinstance(build_incident_store("noop"), NoopIncidentStore)


def test_build_incident_store_defaults_to_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENT_STORE_PATH", str(tmp_path / "incidents.db"))

    assert isinstance(build_incident_store(), IncidentStore)


def test_build_incident_store_rejects_an_unknown_backend():
    with pytest.raises(ValueError, match="wat"):
        build_incident_store("wat")


@pytest.fixture
def cloud_client(monkeypatch, tmp_path):
    monkeypatch.delenv("PHAROS_RAG_ENGINE_TOKEN", raising=False)
    monkeypatch.setitem(main.components, "incident_store", NoopIncidentStore())
    monkeypatch.setitem(main.components, "embedder", StubEmbedder())
    monkeypatch.setitem(main.components, "retriever", StubRetriever())
    monkeypatch.setitem(main.components, "reasoner", StubReasoner())
    monkeypatch.setattr(
        main,
        "settings",
        dataclasses.replace(main.settings, diagnose_log_path=tmp_path / "diagnose_log.jsonl"),
    )
    return TestClient(main.app)


NOT_IMPLEMENTED = {
    "error": "not_implemented_in_cloud_mode",
    "reason": "incident store is noop; Phase 3 provides a persistent backend",
}


def test_approve_returns_501(cloud_client):
    response = cloud_client.post("/incidents/abc123/approve")

    assert response.status_code == 501
    assert response.json() == NOT_IMPLEMENTED


def test_memorize_returns_501(cloud_client):
    response = cloud_client.post("/incidents/abc123/memorize")

    assert response.status_code == 501
    assert response.json() == NOT_IMPLEMENTED


def test_listing_incidents_returns_501(cloud_client):
    response = cloud_client.get("/incidents")

    assert response.status_code == 501
    assert response.json() == NOT_IMPLEMENTED


def test_diagnose_still_works_and_populates_incident_id(cloud_client):
    response = cloud_client.post("/diagnose", json=CONTEXT.model_dump())

    assert response.status_code == 200
    body = response.json()
    assert body["root_cause"] == DIAGNOSIS_JSON["root_cause"]
    assert body["retrieval_relevance_score"] == pytest.approx(0.81)
    assert body["sources_used"] == ["crashloop-backoff.md::Symptom"]
    assert len(body["incident_id"]) == 32


def test_diagnose_ids_are_unique_across_calls(cloud_client):
    first = cloud_client.post("/diagnose", json=CONTEXT.model_dump()).json()
    second = cloud_client.post("/diagnose", json=CONTEXT.model_dump()).json()

    assert first["incident_id"] != second["incident_id"]


def test_health_reports_the_noop_backend(cloud_client):
    body = cloud_client.get("/health").json()

    assert body["status"] == "ok"
    assert body["incident_store_backend"] == "noop"
    assert body["retriever_backend"] == "firestore"
    assert body["corpus_size"] == 60


def test_sqlite_mode_leaves_the_stateful_endpoints_reachable(monkeypatch, tmp_path):
    monkeypatch.delenv("PHAROS_RAG_ENGINE_TOKEN", raising=False)
    monkeypatch.setitem(
        main.components, "incident_store", IncidentStore(tmp_path / "incidents.db")
    )
    client = TestClient(main.app)

    assert client.get("/incidents").status_code == 200
    assert client.post("/incidents/does-not-exist/approve").status_code == 404