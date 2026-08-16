#!/usr/bin/env python3
"""Run the Phase 1f validation dataset through /diagnose and record every result."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "validation" / "dataset" / "incidents.jsonl"
RESULTS_DIR = REPO_ROOT / "validation" / "results"

CONDITION_BACKEND = {"rag_on": "chroma_local", "rag_off": "none"}

DEFAULT_DELAY_SEC = 5.0
RATE_LIMIT_BACKOFF_SEC = 60
REQUEST_TIMEOUT_SEC = 120


NO_RESPONSE = -1


def _post_json(url: str, payload: dict, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return NO_RESPONSE, f"transport error contacting {url}: {e}"


def _get_json(url: str, timeout: int = 10) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return NO_RESPONSE, f"transport error contacting {url}: {e}"


QUOTA_DAILY = "quota_daily"
RATE_LIMITED = "rate_limited"
OTHER_FAILURE = "other"
SCHEMA_INVALID = "schema_invalid"


def classify_failure(status: int, body: str) -> str:
    if status == 200:
        return ""
    blob = body.lower()

    if "unavailable" in blob or "503" in blob or "overloaded" in blob:
        return RATE_LIMITED

    if status == 500 and "schema validation" in blob:
        return SCHEMA_INVALID

    exhausted = (
        "resource_exhausted" in blob
        or ("429" in blob and "quota" in blob)
        or "rate limit" in blob
    )
    if not exhausted:
        return OTHER_FAILURE
    if "perday" in blob or "per day" in blob:
        return QUOTA_DAILY
    if "perminute" in blob or "per minute" in blob:
        return RATE_LIMITED
    return RATE_LIMITED


def preflight(base_url: str, condition: str, allow_unverified: bool) -> None:
    expected = CONDITION_BACKEND[condition]

    status, body = _get_json(f"{base_url}/health")
    if status != 200:
        detail = body if status == NO_RESPONSE else f"returned HTTP {status}"
        sys.exit(
            f"preflight: cannot reach the RAG engine - {detail}\n\n"
            f"Start it in the mode this condition needs:\n"
            f"  cd services/rag-engine && RETRIEVER_BACKEND={expected} \\\n"
            f"    ../../.venv/bin/python -m uvicorn main:app --port 8080"
        )

    try:
        health = json.loads(body)
    except json.JSONDecodeError:
        health = {}

    reported = health.get("retriever_backend")
    if reported is None:
        msg = (
            "preflight: /health does not report retriever_backend, so the harness\n"
            "cannot confirm the server is in the mode this condition requires\n"
            f"(expected {expected!r}).\n"
            "Running both conditions against the same backend yields a\n"
            "meaningless ~0 delta that looks exactly like a real result."
        )
        if not allow_unverified:
            sys.exit(
                msg + "\n\nEither add retriever_backend to /health, or re-run with\n"
                "--allow-unverified-backend if you have checked it by hand."
            )
        print(f"!! {msg}\n!! Continuing because --allow-unverified-backend was given.\n")
        return

    if reported != expected:
        sys.exit(
            f"preflight: ABORT - condition {condition!r} needs "
            f"RETRIEVER_BACKEND={expected!r}, but the server reports {reported!r}.\n"
            f"Restart the RAG engine with RETRIEVER_BACKEND={expected}."
        )

    print(f"preflight: server confirms retriever_backend={reported!r} - matches {condition}")


def load_dataset(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"dataset not found: {path}\nRun validation/dataset/generate_dataset.py first.")
    incidents = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not incidents:
        sys.exit(f"dataset is empty: {path}")
    return incidents


def already_done(output: Path) -> set[str]:
    if not output.exists():
        return set()
    done: set[str] = set()
    for line in output.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("ok") or _is_schema_invalid(record):
            done.add(record["id"])
    return done


def _is_schema_invalid(record: dict) -> bool:
    body = str((record.get("error") or {}).get("body", "")).lower()
    return record.get("http_status") == 500 and "schema validation" in body


def run(args: argparse.Namespace) -> int:
    condition = args.condition
    output = args.output or (RESULTS_DIR / f"{condition}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)

    incidents = load_dataset(args.dataset)
    done = already_done(output)
    pending = [i for i in incidents if i["id"] not in done]

    if done:
        print(f"resume: {len(done)} of {len(incidents)} already completed in {output.name}")
    if not pending:
        print(f"nothing to do - all {len(incidents)} incidents already recorded for {condition}")
        return 0

    attempting = pending if args.limit is None else pending[: args.limit]
    if not attempting:
        print(f"--limit {args.limit}: nothing attempted this session")
        return 0
    print(
        f"condition={condition}  dataset={len(incidents)}  pending={len(pending)}  "
        f"attempting={len(attempting)}  delay={args.delay}s"
    )
    print(f"output: {output}")

    if args.dry_run:
        print("\n--dry-run: no requests will be sent. Would attempt, in order:")
        for inc in attempting:
            print(f"  {inc['id']:<22} ood={str(inc['is_ood']):<5} {inc['expected_root_cause_category']}")
        return 0

    preflight(args.base_url, condition, args.allow_unverified_backend)
    print()

    url = f"{args.base_url}/diagnose"
    started = time.monotonic()
    counts = {"ok": 0, "failed": 0, "schema_invalid": 0}
    exit_code = 0

    with output.open("a", encoding="utf-8", newline="\n") as sink:

        def emit(record: dict) -> None:
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            sink.flush()
            os.fsync(sink.fileno())  # a quota abort must not lose the work above it

        for n, incident in enumerate(attempting, start=1):
            attempt = 0
            schema_invalid = False
            while True:
                attempt += 1
                t0 = time.monotonic()
                status, body = _post_json(url, incident["context"], args.timeout)
                wall_ms = round((time.monotonic() - t0) * 1000, 1)

                if status == 200:
                    break

                kind = classify_failure(status, body)

                if kind == QUOTA_DAILY:
                    emit(_record(incident, condition, status, wall_ms, body, attempt))
                    counts["failed"] += 1
                    print(
                        f"\n[{incident['id']}] DAILY QUOTA EXHAUSTED (HTTP {status}).\n"
                        f"Retrying will not help today - the free-tier per-day cap resets\n"
                        f"on Google's schedule. {counts['ok']} incident(s) completed this\n"
                        f"session and are saved.\n\n"
                        f"Resume tomorrow with the identical command; completed incidents\n"
                        f"are skipped automatically."
                    )
                    exit_code = 2
                    _summary(counts, started, output, done, incidents)
                    return exit_code

                if kind == SCHEMA_INVALID:
                    emit(_record(incident, condition, status, wall_ms, body, attempt))
                    counts["schema_invalid"] += 1
                    print(
                        f"[{n:>2}/{len(attempting)}] {incident['id']:<22} "
                        f"{wall_ms:>8.1f}ms  SCHEMA INVALID after retry (recorded, continuing)"
                    )
                    schema_invalid = True
                    break

                if kind == RATE_LIMITED and attempt == 1:
                    print(
                        f"[{incident['id']}] rate limited (HTTP {status}) - "
                        f"one retry in {RATE_LIMIT_BACKOFF_SEC}s"
                    )
                    time.sleep(RATE_LIMIT_BACKOFF_SEC)
                    continue

                emit(_record(incident, condition, status, wall_ms, body, attempt))
                counts["failed"] += 1
                reason = (
                    "rate limited twice in a row"
                    if kind == RATE_LIMITED
                    else f"unexpected failure (HTTP {status})"
                )
                print(
                    f"\n[{incident['id']}] ABORT - {reason}. No silent failures.\n"
                    f"Response body:\n{body[:1000]}"
                )
                exit_code = 1
                _summary(counts, started, output, done, incidents)
                return exit_code

            if not schema_invalid:
                record = _record(incident, condition, status, wall_ms, body, attempt)
                emit(record)
                counts["ok"] += 1

                diagnosis = record["diagnosis"] or {}
                root_cause = str(diagnosis.get("root_cause", ""))[:58]
                print(
                    f"[{n:>2}/{len(attempting)}] {incident['id']:<22} "
                    f"{wall_ms:>8.1f}ms  "
                    f"score={diagnosis.get('retrieval_relevance_score', 0):.3f}  "
                    f"{root_cause}"
                )

            if n % 10 == 0 and n < len(attempting):
                _progress(n, len(attempting), started, args.delay)

            if n < len(attempting):
                time.sleep(args.delay)

    _summary(counts, started, output, done, incidents)
    return exit_code


def _record(
    incident: dict, condition: str, status: int, wall_ms: float, body: str, attempts: int
) -> dict:
    ok = status == 200
    diagnosis = None
    error = None
    if ok:
        try:
            diagnosis = json.loads(body)
        except json.JSONDecodeError:
            ok = False
            error = {"error": "response was not valid JSON", "body": body[:2000]}
    else:
        error = {"http_status": status, "body": body[:2000]}

    return {
        "id": incident["id"],
        "condition": condition,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "http_status": status,
        "attempts": attempts,
        "wall_ms": wall_ms,
        "expected_root_cause_category": incident["expected_root_cause_category"],
        "expected_runbook": incident["expected_runbook"],
        "is_ood": incident["is_ood"],
        "failure_type": incident["failure_type"],
        "incident_id": (diagnosis or {}).get("incident_id"),
        "diagnosis": diagnosis,
        "error": error,
    }


def _progress(n: int, total: int, started: float, delay: float) -> None:
    elapsed = time.monotonic() - started
    per_request = elapsed / n
    remaining = (total - n) * per_request
    print(
        f"     -- {n}/{total} done in {elapsed / 60:.1f} min "
        f"({per_request:.1f}s each incl. {delay}s delay); "
        f"~{remaining / 60:.1f} min left --"
    )


def _summary(
    counts: dict, started: float, output: Path, done_before: set[str], incidents: list[dict]
) -> None:
    elapsed = time.monotonic() - started
    total_done = len(done_before) + counts["ok"]
    print(
        f"\nsession: {counts['ok']} ok, {counts['failed']} failed, "
        f"{elapsed / 60:.1f} min elapsed"
    )
    print(f"overall: {total_done}/{len(incidents)} incidents recorded in {output.name}")
    if total_done < len(incidents):
        print(f"         {len(incidents) - total_done} remaining - re-run the same command to continue")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--condition", required=True, choices=sorted(CONDITION_BACKEND))
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--output", type=Path, default=None,
                    help="default: validation/results/<condition>.jsonl")
    ap.add_argument("--base-url", default=os.getenv("RAG_ENGINE_URL", "http://localhost:8080"))
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC,
                    help=f"seconds between requests (default {DEFAULT_DELAY_SEC})")
    ap.add_argument("--limit", type=int, default=None,
                    help="attempt at most N new incidents this session (for day-splitting)")
    ap.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT_SEC)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent and exit; spends no quota")
    ap.add_argument("--allow-unverified-backend", action="store_true",
                    help="proceed even if /health does not report retriever_backend")
    args = ap.parse_args()

    sys.exit(run(args))


if __name__ == "__main__":
    main()
