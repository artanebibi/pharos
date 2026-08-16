#!/usr/bin/env python3
"""Generate the hard validation set: 15 in-distribution incidents with indirect evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_dataset import INT, RATIO, _build, serialise  # noqa: E402

SEED = 20260815
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "incidents_hard.jsonl"

import random  # noqa: E402

CRASHLOOP_HARD = [
    {
        "category": "missing_config",
        "logs": [
            "config.load: 3 required fields resolved empty",
            "aborting before listener bind",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {"restart_count": (INT, 6, 12)},
    },
    {
        "category": "missing_config",
        "logs": [],
        "events": [
            "FailedMount: MountVolume.SetUp failed for volume 'app-settings': object not found",
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
        ],
        "metrics": {"restart_count": (INT, 4, 9)},
    },
    {
        "category": "bad_command",
        "logs": [
            "standard_init_linux.go:228: exec user process caused: permission denied",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Pulled: Successfully pulled image in 0.911s",
        ],
        "metrics": {"restart_count": (INT, 8, 15)},
    },
    {
        "category": "bad_command",
        "logs": [
            "run.sh: line 12: unexpected EOF while looking for matching quote",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Created: Created container: {container}",
        ],
        "metrics": {"restart_count": (INT, 5, 11)},
    },
    {
        "category": "dependency_unavailable",
        "logs": [
            "waiting for upstream readiness (attempt 5/5)",
            "deadline exceeded, terminating",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {"restart_count": (INT, 5, 12)},
    },
]

OOM_HARD = [
    {
        "category": "memory_limit_too_low",
        "logs": [],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 5, 10),
            "memory_working_set_ratio": (RATIO, 972, 998),
        },
    },
    {
        "category": "memory_limit_too_low",
        "logs": ["batch 12 of 40 complete"],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Created: Created container: {container}",
        ],
        "metrics": {
            "restart_count": (INT, 3, 8),
            "memory_working_set_ratio": (RATIO, 981, 999),
        },
    },
    {
        "category": "memory_leak",
        "logs": [
            "resident after collection: 412MiB",
            "resident after collection: 638MiB",
            "resident after collection: 861MiB",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 3, 7),
            "memory_working_set_ratio": (RATIO, 948, 992),
        },
    },
    {
        "category": "memory_leak",
        "logs": [
            "cache entries 1204880 evictions 0",
            "cache entries 3811902 evictions 0",
            "cache entries 7104553 evictions 0",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 2, 6),
            "memory_working_set_ratio": (RATIO, 939, 989),
        },
    },
    {
        "category": "runtime_heap_misconfig",
        "logs": [
            "collector overhead: 91% of the last 60s spent reclaiming",
            "allocation stall 4200ms",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 4, 9),
            "memory_working_set_ratio": (RATIO, 958, 997),
        },
    },
]

CPU_HARD = [
    {
        "category": "cpu_limit_too_low",
        "logs": ["p95 latency 1841ms"],
        "events": ["Started: Started container {container}"],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 521, 664),
            "memory_working_set_ratio": (RATIO, 281, 452),
        },
    },
    {
        "category": "cpu_limit_too_low",
        "logs": ["request queue depth 2104"],
        "events": ["Started: Started container {container}"],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 688, 799),
            "memory_working_set_ratio": (RATIO, 233, 401),
        },
    },
    {
        "category": "cpu_limit_too_low",
        "logs": [],
        "events": [
            "Started: Started container {container}",
            "Pulled: Container image already present on machine",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 604, 731),
            "memory_working_set_ratio": (RATIO, 302, 488),
        },
    },
    {
        "category": "bursty_workload",
        "logs": [
            "window 03:00-03:15 exceeded by 610s",
            "carry-over backlog 18400 items",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 611, 754),
            "memory_working_set_ratio": (RATIO, 388, 541),
        },
    },
    {
        "category": "bursty_workload",
        "logs": [
            "scheduled run overlapped with prior execution",
            "duration 903s against median 74s",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 544, 713),
            "memory_working_set_ratio": (RATIO, 254, 433),
        },
    },
]

GROUPS = [
    ("crashloop", "crashloop-backoff.md", "crashloop", CRASHLOOP_HARD),
    ("oom", "oom-kill.md", "oom", OOM_HARD),
    ("cpu_throttle", "cpu-throttle.md", "cpu-throttle", CPU_HARD),
]

GIVEAWAYS = [
    "oomkilled", "out of memory", "outofmemory", "java heap space", "crashloopbackoff",
    "environment variable", "database_url", "no such file or directory", "exec format error",
    "connection refused", "configmap", "hourly", "cron", "budget", "throttling",
]


def build_dataset() -> list[dict]:
    rng = random.Random(SEED)
    incidents: list[dict] = []
    for failure_type, runbook, slug, variants in GROUPS:
        for i, variant in enumerate(variants, start=1):
            incidents.append(
                _build(rng, f"inc-h-{slug}-{i:03d}", failure_type, runbook, False, variant)
            )
    return incidents


def validate(incidents: list[dict]) -> None:
    problems: list[str] = []

    if len(incidents) != 15:
        problems.append(f"expected 15 incidents, got {len(incidents)}")

    ids = [i["id"] for i in incidents]
    if len(set(ids)) != len(ids):
        problems.append("duplicate incident ids")

    pods = [i["context"]["pod_name"] for i in incidents]
    if len(set(pods)) != len(pods):
        problems.append("duplicate pod names")

    for inc in incidents:
        pod = inc["context"]["pod_name"].lower()
        if any(b in pod for b in ("crashloop", "oom", "throttle", "crash", "burner")):
            problems.append(f"{inc['id']}: pod name leaks the failure type")

        blob = " ".join(inc["context"]["logs"] + inc["context"]["events"]).lower()

        if inc["failure_type"] == "crashloop" and "137" in blob:
            problems.append(f"{inc['id']}: crashloop mentions exit 137")

        if inc["failure_type"] == "cpu_throttle":
            if inc["context"]["metrics"].get("restart_count", 0) != 0:
                problems.append(f"{inc['id']}: cpu_throttle with restarts")

        for term in GIVEAWAYS:
            if term in blob:
                problems.append(f"{inc['id']}: evidence states the answer outright ({term!r})")

    if problems:
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        sys.exit(f"generate_hard_dataset: {len(problems)} constraint violation(s)")


def summarise(incidents: list[dict]) -> None:
    print(f"  {len(incidents)} in-distribution incidents")
    by_type: dict[str, list[str]] = {}
    for inc in incidents:
        by_type.setdefault(inc["failure_type"], []).append(
            inc["expected_root_cause_category"])
    for failure_type in sorted(by_type):
        cats = by_type[failure_type]
        breakdown = ", ".join(f"{c}x{cats.count(c)}" for c in sorted(set(cats)))
        print(f"    {failure_type:<14} {len(cats):>2}  ({breakdown})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    incidents = build_dataset()
    validate(incidents)
    payload = serialise(incidents)

    if args.check:
        if not args.output.exists():
            sys.exit(f"--check: {args.output} does not exist")
        if args.output.read_text(encoding="utf-8") != payload:
            sys.exit(f"--check: {args.output} differs from a fresh generation")
        print(f"--check: {args.output} is byte-identical to a fresh generation")
        summarise(incidents)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(payload)

    print(f"wrote {args.output}")
    summarise(incidents)


if __name__ == "__main__":
    main()
