import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "rag-engine"))

import pytest

import main
from incident_store import IncidentStore


@pytest.fixture(autouse=True)
def _wire_incident_store(tmp_path, monkeypatch):
    monkeypatch.setitem(main.components, "incident_store", IncidentStore(tmp_path / "incidents.db"))
