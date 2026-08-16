#!/usr/bin/env python3
"""Incident Memory demo - headline differentiator, measured 5x."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_harness import (  # noqa: E402
    NO_RESPONSE,
    QUOTA_DAILY,
    _get_json,
    _post_json,
    classify_failure,
    preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "validation" / "dataset" / "incidents.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "validation" / "results" / "memory_demo.json"
DEFAULT_ENGINE_LOG = REPO_ROOT / "tests" / "logs" / "diagnose_log.jsonl"

RUNS = 5
DEFAULT_DELAY_SEC = 5.0
ESCALATION = "unknown_failure_mode"


def memory_chunk_id(namespace: str, pod_name: str) -> str:
    return f"incident::{namespace}/{pod_name}"


def select_contexts(dataset: Path, tag: str, runs: int) -> list[dict]:
    incidents = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    in_dist = [i for i in incidents if not i["is_ood"]]
    if len(in_dist) < runs:
        sys.exit(f"need at least {runs} in-distribution incidents, found {len(in_dist)}")

    stride = max(1, len(in_dist) // runs)
    chosen = [in_dist[i * stride] for i in range(runs)]

    contexts = []
    for n, incident in enumerate(chosen, start=1):
        context = json.loads(json.dumps(incident["context"]))  # deep copy
        head = context["pod_name"].rsplit("-", 1)[0]
        context["pod_name"] = f"{head}-{tag}{n}"
        contexts.append({
            "source_incident": incident["id"],
            "failure_type": incident["failure_type"],
            "context": context,
        })
    return contexts


def call(url: str, payload: dict | None, timeout: int, label: str) -> dict:
    status, body = _post_json(url, payload or {}, timeout)
    if status == 200:
        return json.loads(body)

    kind = classify_failure(status, body)
    if kind == QUOTA_DAILY:
        sys.exit(
            f"\n{label}: DAILY QUOTA EXHAUSTED (HTTP {status}).\n"
            f"The demo needs 10 requests in one sitting to keep each run's "
            f"before/after pair comparable, so partial results are not saved.\n"
            f"Re-run tomorrow once the free-tier cap resets."
        )
    detail = body if status == NO_RESPONSE else f"HTTP {status}: {body[:600]}"
    sys.exit(f"\n{label} failed - {detail}")


def retrieved_chunk_ids(log_path: Path, incident_id: str) -> list[str] | None:
    if not incident_id or not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (record.get("diagnosis") or {}).get("incident_id") == incident_id:
            ids = record.get("retrieved_chunk_ids")
            return list(ids) if ids is not None else None
    return None


def run_once(args, spec: dict, index: int) -> dict:
    base = args.base_url
    context = spec["context"]
    chunk_id = memory_chunk_id(context["namespace"], context["pod_name"])

    print(f"\n[run {index}/{RUNS}] {spec['failure_type']:<14} pod={context['pod_name']}")

    first = call(f"{base}/diagnose", context, args.timeout, f"run {index} first diagnose")
    first_score = first.get("retrieval_relevance_score")
    incident_id = first.get("incident_id")
    print(f"  1. diagnose  score={first_score:.3f}  {str(first.get('root_cause'))[:52]}")

    if first.get("root_cause") == ESCALATION:
        print("  !  first diagnosis escalated as out-of-distribution - run aborted")
        return {
            "run": index, "passed": False, "source_incident": spec["source_incident"],
            "failure_type": spec["failure_type"], "pod_name": context["pod_name"],
            "chunk_id": chunk_id, "first_score": first_score, "second_score": None,
            "cited_own_memory": False, "retrieved_own_memory": None,
            "cited_other_memories": [], "corpus_before": None, "corpus_after": None,
            "note": "first diagnosis escalated (OOD); nothing memorised",
        }

    time.sleep(args.delay)
    call(f"{base}/incidents/{incident_id}/approve", None, args.timeout,
         f"run {index} approve")
    print(f"  2. approve   incident_id={incident_id}")

    corpus_before = _corpus_size(base)
    memorized = call(f"{base}/incidents/{incident_id}/memorize", None, args.timeout,
                     f"run {index} memorize")
    corpus_after = memorized.get("corpus_size")
    print(f"  3. memorize  corpus {corpus_before} -> {corpus_after}")

    time.sleep(args.delay)
    second = call(f"{base}/diagnose", context, args.timeout, f"run {index} second diagnose")
    second_score = second.get("retrieval_relevance_score")
    sources = list(second.get("sources_used") or [])

    cited_own = chunk_id in sources
    cited_other = [s for s in sources if s.startswith("incident::") and s != chunk_id]
    chunks = retrieved_chunk_ids(args.engine_log, second.get("incident_id"))
    retrieved_own = None if chunks is None else (chunk_id in chunks)

    delta = (second_score - first_score) if None not in (first_score, second_score) else None
    print(f"  4. diagnose  score={second_score:.3f}"
          + (f"  ({delta:+.3f})" if delta is not None else ""))
    print(f"  5. cites own memory chunk: {cited_own}"
          + ("" if retrieved_own is None else f"  (retrieved: {retrieved_own})"))
    if cited_other:
        print(f"     also cited earlier runs' memories: {cited_other}")

    return {
        "run": index, "passed": cited_own, "source_incident": spec["source_incident"],
        "failure_type": spec["failure_type"], "pod_name": context["pod_name"],
        "chunk_id": chunk_id, "first_score": first_score, "second_score": second_score,
        "cited_own_memory": cited_own, "retrieved_own_memory": retrieved_own,
        "cited_other_memories": cited_other,
        "corpus_before": corpus_before, "corpus_after": corpus_after,
        "sources_used": sources, "note": "",
    }


def _corpus_size(base_url: str) -> int | None:
    status, body = _get_json(f"{base_url}/health")
    if status != 200:
        return None
    try:
        return json.loads(body).get("corpus_size")
    except json.JSONDecodeError:
        return None


def summarise(runs: list[dict]) -> None:
    passed = [r for r in runs if r["passed"]]
    deltas = [r["second_score"] - r["first_score"] for r in runs
              if r["first_score"] is not None and r["second_score"] is not None]

    print("\n" + "=" * 66)
    print(f"Incident Memory demo: {len(passed)}/{len(runs)} runs passed")
    if deltas:
        mean = sum(deltas) / len(deltas)
        print(f"mean relevance increase: {mean:+.3f}  "
              f"(range {min(deltas):+.3f} to {max(deltas):+.3f}, n={len(deltas)})")
    for r in runs:
        mark = "PASS" if r["passed"] else "FAIL"
        scores = (f"{r['first_score']:.3f} -> {r['second_score']:.3f}"
                  if r["second_score"] is not None else "incomplete")
        print(f"  {mark}  run {r['run']} {r['failure_type']:<14} {scores}"
              + (f"   {r['note']}" if r["note"] else ""))

    if len(passed) < len(runs):
        print(
            "\nNot all runs passed. If retrieved_own_memory is True but the run "
            "still failed,\nretrieval worked and the model declined to cite the "
            "chunk - a citation-behaviour\nproblem, not a memory problem. Report "
            "it as found; do not re-run until it passes."
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--engine-log", type=Path, default=DEFAULT_ENGINE_LOG)
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--tag", default=None,
                    help="pod-name suffix keeping invocations distinct "
                         "(default: a UTC timestamp)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and exit; spends no quota")
    ap.add_argument("--allow-unverified-backend", action="store_true")
    args = ap.parse_args()

    tag = args.tag or f"m{int(datetime.now(timezone.utc).timestamp()) % 100000:05d}"
    specs = select_contexts(args.dataset, tag, args.runs)

    print(f"Incident Memory demo - {args.runs} runs, tag={tag!r}, "
          f"{2 * args.runs} Gemini requests")
    for n, spec in enumerate(specs, start=1):
        print(f"  run {n}: {spec['source_incident']:<22} {spec['failure_type']:<14} "
              f"pod={spec['context']['pod_name']}")

    if args.dry_run:
        print("\n--dry-run: nothing sent.")
        return

    preflight(args.base_url, "rag_on", args.allow_unverified_backend)

    runs = [run_once(args, spec, n) for n, spec in enumerate(specs, start=1)]
    summarise(runs)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "runs_requested": args.runs,
        "runs_passed": sum(1 for r in runs if r["passed"]),
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"\nwrote {args.output}")
    print(
        "\nNote: this added one incident-memory chunk per run to the corpus. "
        "They persist -\nthe Retriever interface has no delete. Re-run the "
        "harness only against a corpus\nwhose state you have re-checked."
    )

    sys.exit(0 if all(r["passed"] for r in runs) else 1)


if __name__ == "__main__":
    main()
