import dataclasses
import json

import pytest

import main
from schemas import IncidentContext, RetrievedChunk

RUNBOOK_CHUNK = "crashloop-backoff.md::Root Causes"
MEMORY_CHUNK = "incident::workloads/checkout-api-7f9d"
HALLUCINATED = "Worked example (Pharos simulator):"
FABRICATED_MEMORY = "incident::never/happened"

INCIDENT = IncidentContext(
    pod_name="checkout-api-7f9d",
    namespace="workloads",
    logs=["FATAL: DATABASE_URL environment variable not set"],
    metrics={"restart_count": 6},
    events=["BackOff: Back-off restarting failed container"],
)


class _StubEmbedder:
    def embed_query(self, text):
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


class _StubRetriever:

    def query(self, query_embedding, top_k=5):
        return [
            RetrievedChunk(
                chunk_id=RUNBOOK_CHUNK, document="Root causes of CrashLoopBackOff.",
                metadata={"source": "runbook", "runbook_file": "crashloop-backoff.md",
                          "section": "Root Causes"},
                similarity=0.81,
            ),
            RetrievedChunk(
                chunk_id=MEMORY_CHUNK, document="A previously resolved incident.",
                metadata={"source": "incident_memory"}, similarity=0.74,
            ),
        ]

    def upsert(self, chunk_id, embedding, document, metadata):
        raise AssertionError("upsert must not be called during /diagnose")

    def count(self):
        return 2


def _reasoner_citing(sources):
    class _Reasoner:
        def generate(self, prompt: str) -> str:
            return json.dumps({
                "root_cause": "missing configuration causes the container to exit 1",
                "retrieval_relevance_score": 0.81,
                "severity": "high",
                "remediation_steps": ["Create the missing ConfigMap"],
                "kubectl_commands": ["kubectl rollout restart deployment/x -n workloads"],
                "sources_used": list(sources),
                "reasoning": "Grounded in the retrieved runbook.",
            })

    return _Reasoner()


@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    log_path = tmp_path / "diagnose_log.jsonl"
    monkeypatch.setattr(
        main, "settings", dataclasses.replace(main.settings, diagnose_log_path=log_path)
    )
    return log_path


def _wire(monkeypatch, sources, retriever=None):
    monkeypatch.setitem(main.components, "embedder", _StubEmbedder())
    monkeypatch.setitem(main.components, "retriever", retriever or _StubRetriever())
    monkeypatch.setitem(main.components, "reasoner", _reasoner_citing(sources))


def _last_record(log_path):
    return json.loads(log_path.read_text().strip().splitlines()[-1])


def test_invalid_citations_are_removed_from_the_response(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK, HALLUCINATED, MEMORY_CHUNK])

    diagnosis = main.diagnose(INCIDENT)

    assert diagnosis.sources_used == [RUNBOOK_CHUNK, MEMORY_CHUNK]
    assert HALLUCINATED not in diagnosis.sources_used


def test_response_contract_is_unchanged(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK, HALLUCINATED])

    diagnosis = main.diagnose(INCIDENT)

    assert isinstance(diagnosis.sources_used, list)
    assert all(isinstance(s, str) for s in diagnosis.sources_used)
    assert not hasattr(diagnosis, "hallucinated_citations")


def test_hallucinated_citations_are_logged_not_returned(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK, HALLUCINATED, FABRICATED_MEMORY])

    main.diagnose(INCIDENT)

    record = _last_record(isolated_log)
    assert sorted(record["hallucinated_citations"]) == sorted([HALLUCINATED, FABRICATED_MEMORY])
    assert record["diagnosis"]["sources_used"] == [RUNBOOK_CHUNK]


def test_fabricated_incident_id_does_not_pass_as_valid(monkeypatch, isolated_log):
    _wire(monkeypatch, [FABRICATED_MEMORY])

    diagnosis = main.diagnose(INCIDENT)

    assert diagnosis.sources_used == []
    assert _last_record(isolated_log)["hallucinated_citations"] == [FABRICATED_MEMORY]


def test_citation_validity_rate_counts_valid_over_total(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK, MEMORY_CHUNK, HALLUCINATED, FABRICATED_MEMORY])

    main.diagnose(INCIDENT)

    assert _last_record(isolated_log)["citation_validity_rate"] == pytest.approx(0.5)


def test_all_citations_valid_scores_one(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK, MEMORY_CHUNK])

    main.diagnose(INCIDENT)

    record = _last_record(isolated_log)
    assert record["citation_validity_rate"] == pytest.approx(1.0)
    assert record["hallucinated_citations"] == []


def test_citing_nothing_is_null_not_zero(monkeypatch, isolated_log):
    _wire(monkeypatch, [])

    main.diagnose(INCIDENT)

    record = _last_record(isolated_log)
    assert record["citation_validity_rate"] is None
    assert record["hallucinated_citations"] == []


def test_ood_escalation_logs_an_explicit_null_rate(monkeypatch, isolated_log):
    class _LowScoreRetriever(_StubRetriever):
        def query(self, query_embedding, top_k=5):
            return [
                chunk.model_copy(update={"similarity": 0.05})
                for chunk in super().query(query_embedding, top_k)
            ]

    class _ExplodingReasoner:
        def generate(self, prompt: str) -> str:
            raise AssertionError("must not be called below the OOD floor")

    monkeypatch.setitem(main.components, "embedder", _StubEmbedder())
    monkeypatch.setitem(main.components, "retriever", _LowScoreRetriever())
    monkeypatch.setitem(main.components, "reasoner", _ExplodingReasoner())

    diagnosis = main.diagnose(INCIDENT)

    assert diagnosis.root_cause == "unknown_failure_mode"
    record = _last_record(isolated_log)
    assert "citation_validity_rate" in record
    assert record["citation_validity_rate"] is None
    assert record["hallucinated_citations"] == []


def test_retrieved_chunk_ids_are_logged_in_order(monkeypatch, isolated_log):
    _wire(monkeypatch, [RUNBOOK_CHUNK])

    main.diagnose(INCIDENT)

    assert _last_record(isolated_log)["retrieved_chunk_ids"] == [RUNBOOK_CHUNK, MEMORY_CHUNK]