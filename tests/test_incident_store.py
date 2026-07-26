import pytest

from incident_store import IncidentStore, StatusTransitionError
from schemas import Diagnosis, IncidentContext


def make_context(pod="p1", namespace="workloads"):
    return IncidentContext(pod_name=pod, namespace=namespace, logs=[], metrics={}, events=[])


def make_diagnosis(root_cause="missing config"):
    return Diagnosis(
        root_cause=root_cause,
        retrieval_relevance_score=0.5,
        severity="high",
        remediation_steps=[],
        kubectl_commands=[],
        sources_used=[],
        reasoning="r",
    )


@pytest.fixture
def store(tmp_path):
    return IncidentStore(tmp_path / "incidents.db")


def test_create_and_get_roundtrip(store):
    context = make_context()
    diagnosis = make_diagnosis()

    incident_id = store.create(context, diagnosis, 0.77)
    record = store.get(incident_id)

    assert record is not None
    assert record.id == incident_id
    assert record.status == "PENDING_REVIEW"
    assert record.namespace == "workloads"
    assert record.pod_name == "p1"
    assert record.root_cause == "missing config"
    assert record.retrieval_relevance_score == pytest.approx(0.77)
    assert record.context.pod_name == "p1"
    assert record.diagnosis.root_cause == "missing config"
    assert record.memorized_at is None


def test_identical_incidents_get_distinct_ids(store):
    context = make_context()
    diagnosis = make_diagnosis()

    id1 = store.create(context, diagnosis, 0.5)
    id2 = store.create(context, diagnosis, 0.5)

    assert id1 != id2


def test_get_unknown_id_returns_none(store):
    assert store.get("does-not-exist") is None


def test_every_valid_status_transition(store):
    incident_id = store.create(make_context(), make_diagnosis(), 0.5)

    store.update_status(incident_id, "APPROVED", transition_valid_from={"PENDING_REVIEW"})
    assert store.get(incident_id).status == "APPROVED"

    store.update_status(incident_id, "MEMORIZED", transition_valid_from={"APPROVED"})
    record = store.get(incident_id)
    assert record.status == "MEMORIZED"
    assert record.memorized_at is not None


def test_invalid_transition_pending_to_memorized_directly(store):
    incident_id = store.create(make_context(), make_diagnosis(), 0.5)

    with pytest.raises(StatusTransitionError):
        store.update_status(incident_id, "MEMORIZED", transition_valid_from={"APPROVED"})


def test_invalid_transition_memorized_backwards_to_approved(store):
    incident_id = store.create(make_context(), make_diagnosis(), 0.5)
    store.update_status(incident_id, "APPROVED", transition_valid_from={"PENDING_REVIEW"})
    store.update_status(incident_id, "MEMORIZED", transition_valid_from={"APPROVED"})

    with pytest.raises(StatusTransitionError):
        store.update_status(incident_id, "APPROVED", transition_valid_from={"PENDING_REVIEW"})


def test_list_by_status_filters_correctly(store):
    id_pending = store.create(make_context(pod="a"), make_diagnosis(), 0.5)
    id_approved = store.create(make_context(pod="b"), make_diagnosis(), 0.5)
    id_memorized = store.create(make_context(pod="c"), make_diagnosis(), 0.5)

    store.update_status(id_approved, "APPROVED", transition_valid_from={"PENDING_REVIEW"})
    store.update_status(id_memorized, "APPROVED", transition_valid_from={"PENDING_REVIEW"})
    store.update_status(id_memorized, "MEMORIZED", transition_valid_from={"APPROVED"})

    assert [r.id for r in store.list_by_status("PENDING_REVIEW")] == [id_pending]
    assert [r.id for r in store.list_by_status("APPROVED")] == [id_approved]
    assert [r.id for r in store.list_by_status("MEMORIZED")] == [id_memorized]
