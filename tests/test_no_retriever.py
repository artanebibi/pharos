import dataclasses

import pytest

import main
from config import settings
from retriever import NoRetriever, Retriever, build_retriever
from schemas import IncidentContext


def test_no_retriever_is_a_retriever():
    assert issubclass(NoRetriever, Retriever)
    NoRetriever()


def test_query_returns_no_chunks():
    assert NoRetriever().query([0.1, 0.2, 0.3], top_k=5) == []


def test_max_similarity_over_no_chunks_is_zero():
    chunks = NoRetriever().query([0.1, 0.2, 0.3])
    assert max((c.similarity for c in chunks), default=0.0) == 0.0


def test_upsert_is_a_no_op():
    retriever = NoRetriever()
    retriever.upsert(
        chunk_id="incident::workloads/checkout-api-1",
        embedding=[0.1, 0.2, 0.3],
        document="a resolved incident",
        metadata={"source": "incident_memory"},
    )
    assert retriever.query([0.1, 0.2, 0.3]) == []


def test_count_is_zero():
    assert NoRetriever().count() == 0


def test_selectable_via_config():
    built = build_retriever(dataclasses.replace(settings, retriever_backend="none"))
    assert isinstance(built, NoRetriever)


def test_unknown_backend_still_rejected():
    with pytest.raises(ValueError):
        build_retriever(dataclasses.replace(settings, retriever_backend="nope"))


def test_no_retriever_does_not_reach_chromadb(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name == "chromadb":
            raise AssertionError("NoRetriever must not import chromadb")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    retriever = build_retriever(dataclasses.replace(settings, retriever_backend="none"))
    retriever.query([0.1, 0.2, 0.3])


class _StubEmbedder:
    def embed_query(self, text):
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


class _RecordingReasoner:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            '{"root_cause": "memory limit set too low", '
            '"retrieval_relevance_score": 0.0, "severity": "high", '
            '"remediation_steps": ["Increase the memory limit"], '
            '"kubectl_commands": [], "sources_used": [], '
            '"reasoning": "No retrieval context was available."}'
        )


INCIDENT = IncidentContext(
    pod_name="checkout-api-7f9d",
    namespace="workloads",
    logs=["container killed"],
    metrics={"restart_count": 4},
    events=["BackOff: Back-off restarting failed container"],
)


def test_baseline_reaches_the_model_and_says_it_has_no_grounding(monkeypatch, tmp_path):
    from prompts import NO_RETRIEVAL_NOTICE

    monkeypatch.setattr(
        main, "settings",
        dataclasses.replace(main.settings, diagnose_log_path=tmp_path / "log.jsonl"),
    )
    reasoner = _RecordingReasoner()
    monkeypatch.setitem(main.components, "embedder", _StubEmbedder())
    monkeypatch.setitem(main.components, "retriever", NoRetriever())
    monkeypatch.setitem(main.components, "reasoner", reasoner)

    diagnosis = main.diagnose(INCIDENT)

    assert len(reasoner.prompts) == 1, "the baseline must still call the model"
    assert NO_RETRIEVAL_NOTICE in reasoner.prompts[0]
    assert diagnosis.root_cause != "unknown_failure_mode"
    assert diagnosis.retrieval_relevance_score == 0.0