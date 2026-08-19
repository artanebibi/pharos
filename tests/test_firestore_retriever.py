import dataclasses
import sys
from unittest.mock import MagicMock

import pytest

from config import settings as real_settings
from retriever import (
    DISTANCE_FIELD,
    FirestoreRetriever,
    Retriever,
    build_retriever,
    firestore_document_id,
)


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


@pytest.fixture
def fake_firestore(monkeypatch):
    firestore = MagicMock(name="google.cloud.firestore")
    vector_mod = MagicMock(name="firestore_v1.vector")
    base_vector_query = MagicMock(name="firestore_v1.base_vector_query")

    vector_mod.Vector = MagicMock(name="Vector", side_effect=lambda v: ("Vector", list(v)))

    collection = MagicMock(name="collection")
    firestore.Client.return_value.collection.return_value = collection

    monkeypatch.setitem(sys.modules, "google.cloud.firestore", firestore)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1.vector", vector_mod)
    monkeypatch.setitem(
        sys.modules, "google.cloud.firestore_v1.base_vector_query", base_vector_query
    )

    return firestore, vector_mod, base_vector_query, collection


def _make_retriever(**kwargs):
    return FirestoreRetriever(project="pharos-505715", **kwargs)


def test_runbook_chunk_ids_stay_readable():
    assert firestore_document_id("crashloop-backoff.md::Symptom") == (
        "crashloop-backoff.md::Symptom"
    )


def test_incident_memory_slash_is_encoded():
    encoded = firestore_document_id("incident::workloads/checkout-api-7f9d")

    assert "/" not in encoded
    assert encoded == "incident::workloads%2Fcheckout-api-7f9d"


def test_document_id_is_deterministic():
    chunk_id = "incident::workloads/pod-a"
    assert firestore_document_id(chunk_id) == firestore_document_id(chunk_id)


def test_distinct_chunk_ids_do_not_collide():
    assert firestore_document_id("incident::a/b") != firestore_document_id("incident::a/c")


def test_query_uses_cosine_find_nearest_with_top_k(fake_firestore):
    _, vector_mod, base_vector_query, collection = fake_firestore
    collection.find_nearest.return_value.get.return_value = []

    _make_retriever().query([0.1] * 768, top_k=5)

    kwargs = collection.find_nearest.call_args.kwargs
    assert kwargs["vector_field"] == "embedding"
    assert kwargs["limit"] == 5
    assert kwargs["distance_measure"] is base_vector_query.DistanceMeasure.COSINE
    assert kwargs["distance_result_field"] == DISTANCE_FIELD
    vector_mod.Vector.assert_called_once()


def test_query_converts_cosine_distance_to_similarity(fake_firestore):
    _, _, _, collection = fake_firestore
    collection.find_nearest.return_value.get.return_value = [
        FakeSnapshot(
            "crashloop-backoff.md::Symptom",
            {
                "id": "crashloop-backoff.md::Symptom",
                "document": "CrashLoopBackOff Symptom\n\nPod restarts repeatedly.",
                "source": "runbook",
                "runbook_file": "crashloop-backoff.md",
                "section": "Symptom",
                DISTANCE_FIELD: 0.13,
            },
        ),
        FakeSnapshot(
            "oom-kill.md::Symptom",
            {"id": "oom-kill.md::Symptom", "document": "OOM", "source": "runbook",
             DISTANCE_FIELD: 0.42},
        ),
    ]

    chunks = _make_retriever().query([0.1] * 768, top_k=2)

    assert [c.chunk_id for c in chunks] == [
        "crashloop-backoff.md::Symptom",
        "oom-kill.md::Symptom",
    ]
    assert chunks[0].similarity == pytest.approx(0.87)
    assert chunks[1].similarity == pytest.approx(0.58)


def test_query_strips_reserved_fields_from_metadata(fake_firestore):
    _, _, _, collection = fake_firestore
    collection.find_nearest.return_value.get.return_value = [
        FakeSnapshot(
            "x",
            {
                "id": "x", "document": "text", "embedding": ("Vector", [0.0]),
                DISTANCE_FIELD: 0.2,
                "source": "incident_memory", "ingested_at": "2026-08-16T10:00:00+00:00",
            },
        )
    ]

    chunk = _make_retriever().query([0.1] * 768)[0]

    assert chunk.metadata == {
        "source": "incident_memory",
        "ingested_at": "2026-08-16T10:00:00+00:00",
    }
    assert chunk.document == "text"


def test_query_falls_back_to_the_snapshot_id_when_the_id_field_is_absent(fake_firestore):
    _, _, _, collection = fake_firestore
    collection.find_nearest.return_value.get.return_value = [
        FakeSnapshot("legacy-doc", {"document": "d", DISTANCE_FIELD: 0.5})
    ]

    assert _make_retriever().query([0.1] * 768)[0].chunk_id == "legacy-doc"


def test_empty_result_is_an_empty_list(fake_firestore):
    _, _, _, collection = fake_firestore
    collection.find_nearest.return_value.get.return_value = []

    assert _make_retriever().query([0.1] * 768) == []


def test_upsert_merges_on_the_chunk_id_so_it_is_idempotent(fake_firestore):
    _, vector_mod, _, collection = fake_firestore
    retriever = _make_retriever()

    retriever.upsert(
        chunk_id="crashloop-backoff.md::Remediation",
        embedding=[0.5] * 768,
        document="Remediation text",
        metadata={"source": "runbook", "section": "Remediation"},
    )

    collection.document.assert_called_once_with("crashloop-backoff.md::Remediation")
    payload, kwargs = collection.document.return_value.set.call_args
    assert kwargs["merge"] is True
    assert payload[0]["id"] == "crashloop-backoff.md::Remediation"
    assert payload[0]["document"] == "Remediation text"
    assert payload[0]["source"] == "runbook"
    assert payload[0]["embedding"] == ("Vector", [0.5] * 768)
    vector_mod.Vector.assert_called_once_with([0.5] * 768)


def test_upsert_encodes_the_document_key_for_incident_memory(fake_firestore):
    _, _, _, collection = fake_firestore

    _make_retriever().upsert(
        chunk_id="incident::workloads/checkout-api-7f9d",
        embedding=[0.1] * 768,
        document="Resolved incident",
        metadata={"source": "incident_memory"},
    )

    collection.document.assert_called_once_with("incident::workloads%2Fcheckout-api-7f9d")
    assert (
        collection.document.return_value.set.call_args[0][0]["id"]
        == "incident::workloads/checkout-api-7f9d"
    )


def test_metadata_cannot_shadow_the_document_or_the_vector(fake_firestore):
    _, _, _, collection = fake_firestore

    _make_retriever().upsert(
        chunk_id="c",
        embedding=[0.9] * 768,
        document="the real text",
        metadata={"document": "hijacked", "embedding": "hijacked", "id": "hijacked"},
    )

    payload = collection.document.return_value.set.call_args[0][0]
    assert payload["document"] == "the real text"
    assert payload["embedding"] == ("Vector", [0.9] * 768)
    assert payload["id"] == "c"


def test_upsert_tolerates_empty_metadata(fake_firestore):
    _, _, _, collection = fake_firestore

    _make_retriever().upsert(chunk_id="c", embedding=[0.1], document="d", metadata={})

    assert collection.document.return_value.set.call_args[0][0]["id"] == "c"


def test_count_uses_the_aggregation_query(fake_firestore):
    _, _, _, collection = fake_firestore
    collection.count.return_value.get.return_value = [[MagicMock(value=60)]]

    assert _make_retriever().count() == 60
    collection.count.assert_called_once_with()


def test_build_retriever_selects_firestore_from_settings(fake_firestore):
    firestore, _, _, _ = fake_firestore
    settings = dataclasses.replace(
        real_settings,
        retriever_backend="firestore",
        gcp_project="pharos-505715",
        firestore_database="(default)",
        firestore_collection="pharos_corpus",
    )

    built = build_retriever(settings)

    assert isinstance(built, FirestoreRetriever)
    assert isinstance(built, Retriever)
    assert built.backend_name == "firestore"
    assert built.performs_retrieval is True
    firestore.Client.assert_called_once_with(project="pharos-505715", database="(default)")
    firestore.Client.return_value.collection.assert_called_once_with("pharos_corpus")


def test_build_retriever_rejects_an_unknown_backend():
    settings = dataclasses.replace(real_settings, retriever_backend="wat")

    with pytest.raises(ValueError, match="wat"):
        build_retriever(settings)