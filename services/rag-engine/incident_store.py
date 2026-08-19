from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import REPO_ROOT
from schemas import Diagnosis, IncidentContext

DEFAULT_DB_PATH = REPO_ROOT / "local" / "data" / "incidents.db"


class StatusTransitionError(Exception):
    pass


@dataclass(frozen=True)
class IncidentRecord:
    id: str
    created_at: str
    memorized_at: str | None
    status: str
    namespace: str
    pod_name: str
    root_cause: str
    retrieval_relevance_score: float
    context: IncidentContext
    diagnosis: Diagnosis


class IncidentStore:
    backend_name = "sqlite"

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(os.getenv("INCIDENT_STORE_PATH", str(DEFAULT_DB_PATH)))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    memorized_at TEXT,
                    status TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    pod_name TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    retrieval_relevance_score REAL NOT NULL,
                    context_json TEXT NOT NULL,
                    diagnosis_json TEXT NOT NULL
                )
                """
            )

    def create(self, context: IncidentContext, diagnosis: Diagnosis, score: float) -> str:
        incident_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO incidents "
                "(id, created_at, memorized_at, status, namespace, pod_name, "
                " root_cause, retrieval_relevance_score, context_json, diagnosis_json) "
                "VALUES (?, ?, NULL, 'PENDING_REVIEW', ?, ?, ?, ?, ?, ?)",
                (
                    incident_id,
                    created_at,
                    context.namespace,
                    context.pod_name,
                    diagnosis.root_cause,
                    score,
                    context.model_dump_json(),
                    diagnosis.model_dump_json(),
                ),
            )
        return incident_id

    def get(self, incident_id: str) -> IncidentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def update_status(
        self, incident_id: str, new_status: str, transition_valid_from: set[str]
    ) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            current = row["status"]
            if current not in transition_valid_from:
                raise StatusTransitionError(
                    f"cannot transition incident {incident_id} from "
                    f"{current!r} to {new_status!r}"
                )
            if new_status == "MEMORIZED":
                conn.execute(
                    "UPDATE incidents SET status = ?, memorized_at = ? WHERE id = ?",
                    (new_status, datetime.now(timezone.utc).isoformat(), incident_id),
                )
            else:
                conn.execute(
                    "UPDATE incidents SET status = ? WHERE id = ?",
                    (new_status, incident_id),
                )

    def list_by_status(self, status: str) -> list[IncidentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]


class NoopIncidentStore:

    backend_name = "noop"

    def create(self, context: IncidentContext, diagnosis: Diagnosis, score: float) -> str:
        return uuid.uuid4().hex

    def get(self, incident_id: str) -> IncidentRecord | None:
        raise NotImplementedError("incident store is noop; Phase 3 provides a persistent backend")

    def update_status(
        self, incident_id: str, new_status: str, transition_valid_from: set[str]
    ) -> None:
        raise NotImplementedError("incident store is noop; Phase 3 provides a persistent backend")

    def list_by_status(self, status: str) -> list[IncidentRecord]:
        raise NotImplementedError("incident store is noop; Phase 3 provides a persistent backend")


def build_incident_store(backend: str = "sqlite"):
    if backend == "sqlite":
        return IncidentStore()
    if backend == "noop":
        return NoopIncidentStore()
    raise ValueError(
        f"Unknown INCIDENT_STORE_BACKEND={backend!r} (expected 'sqlite' or 'noop')"
    )


def _row_to_record(row: sqlite3.Row) -> IncidentRecord:
    return IncidentRecord(
        id=row["id"],
        created_at=row["created_at"],
        memorized_at=row["memorized_at"],
        status=row["status"],
        namespace=row["namespace"],
        pod_name=row["pod_name"],
        root_cause=row["root_cause"],
        retrieval_relevance_score=row["retrieval_relevance_score"],
        context=IncidentContext.model_validate_json(row["context_json"]),
        diagnosis=Diagnosis.model_validate_json(row["diagnosis_json"]),
    )