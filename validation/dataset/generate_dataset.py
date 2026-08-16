#!/usr/bin/env python3
"""Generate the Phase 1f validation dataset: 30 labelled synthetic incidents."""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SEED = 20260804

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "incidents.jsonl"

SERVICES = [
    "checkout-api", "ledger-worker", "session-store", "search-indexer",
    "notify-dispatch", "cart-service", "pricing-engine", "auth-gateway",
    "report-builder", "feed-aggregator", "invoice-sync", "profile-api",
    "queue-consumer", "asset-service", "recommend-api", "audit-writer",
    "tally-worker", "route-planner", "stock-tracker", "mail-relay",
    "token-issuer", "batch-runner", "geo-lookup", "trace-collector",
    "config-server", "webhook-relay", "digest-worker", "shard-router",
    "usage-meter", "policy-engine",
]

NAMESPACES = [
    "workloads", "payments", "checkout", "platform", "identity",
    "search", "notifications", "billing", "inventory", "logistics",
]

_RS_ALPHABET = "0123456789abcdef"
_POD_ALPHABET = "bcdfghjklmnpqrstvwxz2456789"

INT = "int"
RATIO = "ratio"  # drawn in thousandths, emitted as a 3-dp float


CRASHLOOP_VARIANTS = [
    {
        "category": "missing_config",
        "logs": [
            "starting {service} v2.14.0",
            "FATAL: required environment variable DATABASE_URL is not set",
            "shutting down after configuration error",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Created: Created container: {container}",
            "Pulled: Container image already present on machine",
        ],
        "metrics": {"restart_count": (INT, 5, 11)},
    },
    {
        "category": "missing_config",
        "logs": [
            "loading settings from /etc/{service}/settings.yaml",
            "error: key 'redis.endpoint' absent from mounted ConfigMap {service}-settings",
            "startup aborted, exit status 1",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {"restart_count": (INT, 3, 9)},
    },
    {
        "category": "bad_command",
        "logs": [
            "exec /usr/local/bin/{service}-serve: no such file or directory",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Created: Created container: {container}",
            "Pulled: Successfully pulled image in 1.204s",
        ],
        "metrics": {"restart_count": (INT, 7, 15)},
    },
    {
        "category": "bad_command",
        "logs": [
            "standard_init_linux.go:228: exec user process caused: exec format error",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Pulled: Successfully pulled image in 3.881s",
        ],
        "metrics": {"restart_count": (INT, 4, 10)},
    },
    {
        "category": "dependency_unavailable",
        "logs": [
            "connecting to primary datastore at 10.96.{octet}.14:5432",
            "dial tcp 10.96.{octet}.14:5432: connect: connection refused",
            "retry 3 of 3 failed, giving up and exiting",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {"restart_count": (INT, 6, 13)},
    },
]

OOM_VARIANTS = [
    {
        "category": "memory_limit_too_low",
        "logs": [
            "worker pool online, 8 threads",
            "processing batch 41 (18400 records)",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {
            "restart_count": (INT, 4, 9),
            "memory_working_set_ratio": (RATIO, 961, 999),
        },
    },
    {
        "category": "memory_limit_too_low",
        "logs": [
            "importing snapshot segment 7/12",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 2, 7),
            "memory_working_set_ratio": (RATIO, 974, 999),
        },
    },
    {
        "category": "memory_leak",
        "logs": [
            "resident set 512MiB after 2h uptime",
            "resident set 794MiB after 4h uptime",
            "resident set 1043MiB after 6h uptime, no plateau observed",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 3, 8),
            "memory_working_set_ratio": (RATIO, 952, 996),
        },
    },
    {
        "category": "memory_leak",
        "logs": [
            "response cache entries=1840219 evictions=0",
            "response cache entries=2733880 evictions=0",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {
            "restart_count": (INT, 2, 6),
            "memory_working_set_ratio": (RATIO, 943, 993),
        },
    },
    {
        "category": "runtime_heap_misconfig",
        "logs": [
            "Exception in thread \"pool-2-thread-9\" java.lang.OutOfMemoryError: Java heap space",
            "\tat com.{service_pkg}.Aggregator.merge(Aggregator.java:212)",
        ],
        "events": [
            "BackOff: Back-off restarting failed container {container} in pod {pod}_{ns}({uid})",
            "Started: Started container {container}",
        ],
        "metrics": {
            "restart_count": (INT, 3, 9),
            "memory_working_set_ratio": (RATIO, 966, 999),
        },
    },
]

CPU_THROTTLE_VARIANTS = [
    {
        "category": "cpu_limit_too_low",
        "logs": [
            "handler /v1/quote completed in 2841ms (budget 400ms)",
            "handler /v1/quote completed in 3122ms (budget 400ms)",
        ],
        "events": [
            "Started: Started container {container}",
            "Created: Created container: {container}",
            "Pulled: Container image already present on machine",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 512, 690),
            "memory_working_set_ratio": (RATIO, 291, 470),
        },
    },
    {
        "category": "cpu_limit_too_low",
        "logs": [
            "p99 latency 4.19s exceeds SLO 1.00s for 12 consecutive windows",
        ],
        "events": [
            "Started: Started container {container}",
            "Pulled: Container image already present on machine",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 681, 812),
            "memory_working_set_ratio": (RATIO, 224, 388),
        },
    },
    {
        "category": "cpu_limit_too_low",
        "logs": [
            "work queue depth 4180 and rising, consumers unable to keep pace",
            "mean service time degraded from 38ms to 611ms",
        ],
        "events": [
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 447, 601),
            "memory_working_set_ratio": (RATIO, 316, 502),
        },
    },
    {
        "category": "bursty_workload",
        "logs": [
            "hourly reconciliation started, 240000 rows queued",
            "reconciliation window overran by 480s",
        ],
        "events": [
            "Started: Started container {container}",
            "Pulled: Container image already present on machine",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 604, 748),
            "memory_working_set_ratio": (RATIO, 402, 559),
        },
    },
    {
        "category": "bursty_workload",
        "logs": [
            "scheduled export triggered at :00, prior export still draining",
            "export duration 903s (median 74s)",
        ],
        "events": [
            "Started: Started container {container}",
            "Created: Created container: {container}",
        ],
        "metrics": {
            "restart_count": (INT, 0, 0),
            "cpu_throttle_ratio": (RATIO, 538, 707),
            "memory_working_set_ratio": (RATIO, 268, 441),
        },
    },
]


OOD_VARIANTS = [
    {
        "category": "dns_resolution_failure",
        "logs": [
            "lookup ledger.internal on 10.96.0.10:53: no such host",
            "upstream call abandoned after 5 resolution attempts",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 201, 402)},
    },
    {
        "category": "dns_resolution_failure",
        "logs": [
            "SERVFAIL received from 10.96.0.10 for query pricing.svc.cluster.local",
            "falling back to cached endpoint list (stale 940s)",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 188, 371)},
    },
    {
        "category": "dns_resolution_failure",
        "logs": [
            "resolver exhausted search path after 8 queries for host 'gateway'",
            "ndots setting is causing every short name to fan out",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 233, 415)},
    },
    {
        "category": "image_pull_error",
        "logs": [],
        "events": [
            "Failed: Failed to pull image: rpc error: code = Unknown desc = pull access denied, repository does not exist or may require authorisation",
            "Failed: Error: ErrImagePull",
            "BackOff: Back-off pulling image",
        ],
        "metrics": {"restart_count": (INT, 0, 0)},
    },
    {
        "category": "image_pull_error",
        "logs": [],
        "events": [
            "Failed: Failed to pull image: manifest for tag v3.9.1-rc4 not found",
            "Failed: Error: ImagePullBackOff",
            "Pulling: Pulling image",
        ],
        "metrics": {"restart_count": (INT, 0, 0)},
    },
    {
        "category": "image_pull_error",
        "logs": [],
        "events": [
            "Failed: Failed to pull image: dial tcp: i/o timeout contacting private registry",
            "Failed: Error: ErrImagePull",
            "Pulling: Pulling image",
        ],
        "metrics": {"restart_count": (INT, 0, 0)},
    },
    {
        "category": "network_policy_block",
        "logs": [
            "POST https://ledger.payments.svc:8443/v1/post - context deadline exceeded after 10s",
            "0 of 6 downstream calls completed in the last minute",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 244, 431)},
    },
    {
        "category": "network_policy_block",
        "logs": [
            "inbound connections from namespace 'search' rejected before TLS handshake",
            "peer sent no data, socket closed by intermediary",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 197, 366)},
    },
    {
        "category": "network_policy_block",
        "logs": [
            "egress to 34.117.0.0/16 silently dropped, no RST observed",
            "health of external dependency unknown for 14 minutes",
        ],
        "events": ["Started: Started container {container}"],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 212, 398)},
    },
    {
        "category": "pvc_binding_failure",
        "logs": [],
        "events": [
            "FailedScheduling: 0/3 nodes are available: pod has unbound immediate PersistentVolumeClaims",
            "ProvisioningFailed: storageclass.storage.k8s.io 'fast-ssd' not found",
        ],
        "metrics": {},
    },
    {
        "category": "pvc_binding_failure",
        "logs": [],
        "events": [
            "FailedScheduling: 0/3 nodes are available: 3 node(s) had volume node affinity conflict",
            "WaitForFirstConsumer: waiting for first consumer to be created before binding",
        ],
        "metrics": {},
    },
    {
        "category": "pvc_binding_failure",
        "logs": [],
        "events": [
            "FailedAttachVolume: Multi-Attach error for volume - already exclusively attached to another node",
            "FailedMount: Unable to attach or mount volumes: timed out waiting for the condition",
        ],
        "metrics": {},
    },
    {
        "category": "hpa_not_scaling",
        "logs": [
            "sustained inbound rate 1840 rps against 2 replicas",
            "admission queue saturated for 9 consecutive minutes",
        ],
        "events": [
            "FailedGetResourceMetric: unable to get metrics for resource cpu: no metrics returned from resource metrics API",
            "FailedComputeMetricsReplicas: invalid metrics (1 invalid out of 1)",
        ],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 381, 566)},
    },
    {
        "category": "hpa_not_scaling",
        "logs": [
            "replica count pinned at 3 while offered load tripled",
        ],
        "events": [
            "FailedGetExternalMetric: unable to get external metric queue_depth: no metric registered",
            "ScalingLimited: the desired replica count is less than the minimum replica count",
        ],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 344, 512)},
    },
    {
        "category": "hpa_not_scaling",
        "logs": [
            "backlog age 22m and growing, worker concurrency unchanged",
        ],
        "events": [
            "FailedGetResourceMetric: missing request for cpu in container spec, target utilisation cannot be computed",
            "ScalingActive: False - the autoscaler could not compute a desired replica count",
        ],
        "metrics": {"restart_count": (INT, 0, 0), "memory_working_set_ratio": (RATIO, 407, 588)},
    },
]

IN_DISTRIBUTION = [
    ("crashloop", "crashloop-backoff.md", "crashloop", CRASHLOOP_VARIANTS),
    ("oom", "oom-kill.md", "oom", OOM_VARIANTS),
    ("cpu_throttle", "cpu-throttle.md", "cpu-throttle", CPU_THROTTLE_VARIANTS),
]

OOD_ID_SLUGS = {
    "dns_resolution_failure": "dns",
    "image_pull_error": "imagepull",
    "network_policy_block": "netpol",
    "pvc_binding_failure": "pvc",
    "hpa_not_scaling": "hpa",
}


def _pod_name(rng: random.Random, service: str) -> str:
    rs = "".join(rng.choice(_RS_ALPHABET) for _ in range(10))
    suffix = "".join(rng.choice(_POD_ALPHABET) for _ in range(5))
    return f"{service}-{rs}-{suffix}"


def _uid(rng: random.Random) -> str:
    return "".join(rng.choice(_RS_ALPHABET) for _ in range(8))


def _draw_metrics(rng: random.Random, spec: dict) -> dict:
    out: dict[str, float | int] = {}
    for key, (kind, lo, hi) in spec.items():
        n = rng.randint(lo, hi)
        out[key] = n if kind == INT else round(n / 1000, 3)
    return out


def _render(templates: list[str], **fields) -> list[str]:
    return [t.format(**fields) for t in templates]


def _build(
    rng: random.Random,
    incident_id: str,
    failure_type: str,
    expected_runbook: str | None,
    is_ood: bool,
    variant: dict,
) -> dict:
    service = rng.choice(SERVICES)
    namespace = rng.choice(NAMESPACES)
    pod = _pod_name(rng, service)
    fields = {
        "service": service,
        "service_pkg": service.replace("-", ""),
        "container": service,
        "pod": pod,
        "ns": namespace,
        "uid": _uid(rng),
        "octet": rng.randint(11, 240),
    }

    return {
        "id": incident_id,
        "failure_type": failure_type,
        "expected_root_cause_category": variant["category"],
        "expected_runbook": expected_runbook,
        "is_ood": is_ood,
        "context": {
            "namespace": namespace,
            "pod_name": pod,
            "logs": _render(variant["logs"], **fields),
            "metrics": _draw_metrics(rng, variant["metrics"]),
            "events": _render(variant["events"], **fields),
        },
    }


def build_dataset() -> list[dict]:
    rng = random.Random(SEED)
    incidents: list[dict] = []

    for failure_type, runbook, slug, variants in IN_DISTRIBUTION:
        for i, variant in enumerate(variants, start=1):
            incidents.append(
                _build(rng, f"inc-{slug}-{i:03d}", failure_type, runbook, False, variant)
            )

    counters: dict[str, int] = {}
    for variant in OOD_VARIANTS:
        category = variant["category"]
        counters[category] = counters.get(category, 0) + 1
        slug = OOD_ID_SLUGS[category]
        incidents.append(
            _build(
                rng,
                f"inc-{slug}-{counters[category]:03d}",
                category,      # OOD incidents use the category as failure_type
                None,          # no runbook exists - that is what makes them OOD
                True,
                variant,
            )
        )

    return incidents


def serialise(incidents: list[dict]) -> str:
    return "".join(json.dumps(inc, ensure_ascii=False) + "\n" for inc in incidents)


def validate(incidents: list[dict]) -> None:
    problems: list[str] = []

    if len(incidents) != 30:
        problems.append(f"expected 30 incidents, got {len(incidents)}")

    ids = [inc["id"] for inc in incidents]
    if len(set(ids)) != len(ids):
        problems.append("duplicate incident ids")

    pods = [inc["context"]["pod_name"] for inc in incidents]
    if len(set(pods)) != len(pods):
        problems.append("duplicate pod names - retrieval could key on them")

    banned = ("crashloop", "oom", "throttle", "crash", "memory-eater", "burner")
    for inc in incidents:
        pod = inc["context"]["pod_name"].lower()
        if any(b in pod for b in banned):
            problems.append(f"{inc['id']}: pod name leaks the failure type")

    for inc in incidents:
        if inc["failure_type"] == "cpu_throttle":
            if inc["context"]["metrics"].get("restart_count", 0) != 0:
                problems.append(f"{inc['id']}: cpu_throttle with restarts")

    for inc in incidents:
        if inc["failure_type"] == "crashloop":
            blob = " ".join(inc["context"]["logs"] + inc["context"]["events"])
            if "137" in blob:
                problems.append(f"{inc['id']}: crashloop mentions exit 137")

    ood_banned = ("oomkilled", "out of memory", "outofmemory", "crashloopbackoff",
                  "back-off restarting", "throttl", "cfs")
    for inc in incidents:
        if not inc["is_ood"]:
            continue
        blob = " ".join(inc["context"]["logs"] + inc["context"]["events"]).lower()
        for term in ood_banned:
            if term in blob:
                problems.append(f"{inc['id']}: OOD evidence contains {term!r}")
        if "cpu_throttle_ratio" in inc["context"]["metrics"]:
            problems.append(f"{inc['id']}: OOD metrics include cpu_throttle_ratio")

    if problems:
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        sys.exit(f"generate_dataset: {len(problems)} constraint violation(s)")


def summarise(incidents: list[dict]) -> None:
    in_dist = [i for i in incidents if not i["is_ood"]]
    ood = [i for i in incidents if i["is_ood"]]
    print(f"  {len(incidents)} incidents - {len(in_dist)} in-distribution, {len(ood)} OOD")

    by_type: dict[str, list[str]] = {}
    for inc in incidents:
        by_type.setdefault(inc["failure_type"], []).append(inc["expected_root_cause_category"])
    for failure_type in sorted(by_type):
        cats = by_type[failure_type]
        breakdown = ", ".join(
            f"{c}x{cats.count(c)}" for c in sorted(set(cats))
        )
        print(f"    {failure_type:<24} {len(cats):>2}  ({breakdown})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--check", action="store_true",
        help="regenerate in memory and diff against --output; exit 1 on drift",
    )
    args = ap.parse_args()

    incidents = build_dataset()
    validate(incidents)
    payload = serialise(incidents)

    if args.check:
        if not args.output.exists():
            sys.exit(f"--check: {args.output} does not exist")
        on_disk = args.output.read_text(encoding="utf-8")
        if on_disk != payload:
            sys.exit(
                f"--check: {args.output} differs from freshly generated output "
                f"({len(on_disk)} bytes on disk vs {len(payload)} generated)"
            )
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