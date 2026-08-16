#!/usr/bin/env python3
"""Compute every metric from grades.csv and write validation/report.md."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "validation" / "results"
DEFAULT_GRADES = RESULTS_DIR / "grades.csv"
DEFAULT_DATASET = REPO_ROOT / "validation" / "dataset" / "incidents.jsonl"
DEFAULT_MEMORY_DEMO = RESULTS_DIR / "memory_demo.json"
DEFAULT_REPORT = REPO_ROOT / "validation" / "report.md"
SCATTER_CSV = RESULTS_DIR / "relevance_vs_correctness.csv"
PLOTS_DIR = RESULTS_DIR / "plots"

CONDITIONS = ("rag_on", "rag_off")
SUCCESS_GRADES = ("CORRECT", "PARTIALLY_CORRECT")
TOP_K = 5
CHUNKS_PER_RUNBOOK = 4
PRECISION_CEILING = CHUNKS_PER_RUNBOOK / TOP_K

NA = "not available"


def as_bool(cell: str) -> bool | None:
    return {"true": True, "false": False}.get((cell or "").strip().lower())


def as_float(cell) -> float | None:
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{100 * numerator / denominator:.1f}%"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))
    return ordered[rank - 1]


@dataclass
class ConditionMetrics:
    condition: str
    rows: list[dict]

    in_dist: list[dict] = field(default_factory=list)
    ood: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.in_dist = [r for r in self.rows if as_bool(r["is_ood"]) is False]
        self.ood = [r for r in self.rows if as_bool(r["is_ood"]) is True]


    def count(self, rows: list[dict], *grades: str) -> int:
        return sum(1 for r in rows if r["grade"] in grades)

    @property
    def n_in_dist(self) -> int:
        return len(self.in_dist)

    @property
    def successes(self) -> int:
        return self.count(self.in_dist, *SUCCESS_GRADES)

    @property
    def strict_successes(self) -> int:
        return self.count(self.in_dist, "CORRECT")

    @property
    def escalated_in_dist(self) -> int:
        return self.count(self.in_dist, "ESCALATED")

    @property
    def errors_in_dist(self) -> int:
        return self.count(self.in_dist, "ERROR")

    @property
    def pending_human(self) -> int:
        return self.count(self.rows, "NEEDS_HUMAN")

    @property
    def primary_success_rate(self) -> float | None:
        if not self.n_in_dist:
            return None
        return self.successes / self.n_in_dist

    @property
    def conditional_denominator(self) -> int:
        return self.n_in_dist - self.escalated_in_dist - self.errors_in_dist

    @property
    def conditional_accuracy(self) -> float | None:
        denom = self.conditional_denominator
        return self.successes / denom if denom > 0 else None

    @property
    def ood_escalation_rate(self) -> float | None:
        return self.count(self.ood, "ESCALATED") / len(self.ood) if self.ood else None


    def latencies(self) -> list[float]:
        return [v for v in (as_float(r["latency_ms"]) for r in self.rows) if v is not None]

    def schema_compliance(self) -> tuple[int, int]:
        flags = [as_bool(r["first_try_schema_ok"]) for r in self.rows]
        considered = [f for f in flags if f is not None]
        return sum(considered), len(considered)

    def citation_rates(self) -> list[float]:
        return [
            v for v in (as_float(r["citation_validity_rate"]) for r in self.in_dist)
            if v is not None
        ]

    def retrieval_scores(self, labels: dict[str, dict]) -> tuple[list[float], list[float]]:
        precisions: list[float] = []
        reciprocal_ranks: list[float] = []
        for row in self.in_dist:
            raw = (row.get("retrieved_chunk_ids") or "").strip()
            if not raw:
                continue
            expected = labels[row["incident_id"]]["expected_runbook"]
            if not expected:
                continue
            ids = raw.split(";")
            hits = [i for i, cid in enumerate(ids, start=1)
                    if cid.split("::", 1)[0] == expected]
            precisions.append(len(hits) / TOP_K)
            reciprocal_ranks.append(1 / hits[0] if hits else 0.0)
        return precisions, reciprocal_ranks


def section_headline(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = ["## The headline: does retrieval help?", ""]

    on = by_condition.get("rag_on")
    off = by_condition.get("rag_off")
    if not on or not off or on.primary_success_rate is None or off.primary_success_rate is None:
        out += [
            f"**RAG-vs-no-RAG delta: {NA}** - both conditions must be graded first "
            f"(have: {', '.join(sorted(by_condition)) or 'none'}).",
            "",
        ]
        return out

    delta = on.primary_success_rate - off.primary_success_rate
    direction = "higher" if delta > 0 else ("lower" if delta < 0 else "identical")

    out += [
        f"**Retrieval on: {on.primary_success_rate:.1%}  "
        f"retrieval off: {off.primary_success_rate:.1%}  "
        f"delta: {delta:+.1%}**  (n={on.n_in_dist} in-distribution incidents per condition)",
        "",
        f"End-to-end success is {direction} with retrieval enabled. The two runs "
        f"used the same dataset, the same model at the same temperature, and the "
        f"same prompt template minus the retrieved chunks - retrieval is the only "
        f"variable that differs, which is what makes this delta attributable to it.",
        "",
        f"> **n={on.n_in_dist} per condition.** With a dataset this size a single "
        f"incident moves the rate by {100 / on.n_in_dist:.1f} percentage points. "
        f"The delta indicates a direction, not an effect size, and no confidence "
        f"interval is claimed.",
        "",
    ]
    if delta <= 0:
        out += [
            "> The delta is not positive. Per docs/phase-1f.md this is reported as "
            "found rather than adjusted - but it is also a signal worth "
            "investigating in the corpus, the chunking, or the embedding before "
            "the result is written up as a property of RAG in general.",
            "",
        ]
    return out


def section_success(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = [
        "## 1. End-to-end success rate",
        "",
        "In-distribution incidents only. "
        "Success = CORRECT or PARTIALLY_CORRECT.",
        "",
        "| Condition | Primary success | Strict (CORRECT only) | Conditional accuracy | Escalated | Errors | n |",
        "|---|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        m = by_condition.get(condition)
        if not m:
            out.append(f"| `{condition}` | {NA} | - | - | - | - | 0 |")
            continue
        conditional = (
            f"{m.conditional_accuracy:.1%} (n={m.conditional_denominator})"
            if m.conditional_accuracy is not None else "n/a"
        )
        out.append(
            f"| `{condition}` | **{m.primary_success_rate:.1%}** "
            f"({m.successes}/{m.n_in_dist}) | "
            f"{m.strict_successes / m.n_in_dist:.1%} | {conditional} | "
            f"{m.escalated_in_dist} | {m.errors_in_dist} | {m.n_in_dist} |"
        )

    out += [
        "",
        "**Primary** keeps escalations and errors in the denominator; **conditional** "
        "removes them and is reported with its own n. Both appear because they can "
        "differ sharply: on the conditional convention alone, a system that escalated "
        "14 of 15 incidents and got the last one right would report 100%.",
        "",
    ]
    return out


def section_retrieval(by_condition: dict[str, ConditionMetrics],
                      labels: dict[str, dict]) -> list[str]:
    out = ["## 2. Retrieval quality (Precision@5, MRR)", ""]

    m = by_condition.get("rag_on")
    precisions, rranks = m.retrieval_scores(labels) if m else ([], [])

    if not precisions:
        out += [
            f"**{NA}.** Precision@5 and MRR are computed from the ordered chunk ids "
            "the retriever returned, which the /diagnose response does not carry - "
            "`sources_used` is the model's citation behaviour, not the retriever's "
            "output. The `retrieved_chunk_ids` column of grades.csv is "
            "empty, which means the RAG engine's log does not yet record them.",
            "",
            "Not approximated from `sources_used`: that would measure the model, "
            "label it as retrieval, and quietly invalidate the metric.",
            "",
        ]
        return out

    out += [
        f"Against the labelled incident->runbook mapping, `rag_on` only, "
        f"n={len(precisions)} in-distribution incidents.",
        "",
        f"- **Precision@5: {statistics.mean(precisions):.3f}** "
        f"(ceiling {PRECISION_CEILING:.2f})",
        f"- **MRR: {statistics.mean(rranks):.3f}**",
        f"- Correct runbook retrieved at all: "
        f"{pct(sum(1 for r in rranks if r > 0), len(rranks))}",
        "",
        f"> **The Precision@5 ceiling is {PRECISION_CEILING:.2f}, not 1.0.** Each "
        f"runbook contributes exactly {CHUNKS_PER_RUNBOOK} chunks to the corpus "
        f"(Symptom / Root Causes / Diagnosis Steps / Remediation), so at most "
        f"{CHUNKS_PER_RUNBOOK} of {TOP_K} retrieved slots can belong to the expected "
        f"runbook. A perfect retriever scores {PRECISION_CEILING:.2f} here. Read the "
        f"figure against that ceiling, not against 1.0.",
        "",
        "> Incident-memory chunks in the corpus at run time count as non-matching: "
        "they are not runbook chunks and cannot satisfy `expected_runbook`.",
        "",
    ]
    return out


def section_ood(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = [
        "## 3. Out-of-distribution behaviour",
        "",
        "The OOD floor's job is to escalate what the corpus cannot ground "
        ". Both sides of that trade are reported: what it catches, "
        "and what it wrongly rejects.",
        "",
        "| Condition | OOD escalation rate | False escalation (in-dist) | Answered anyway: plausible / wrong |",
        "|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        m = by_condition.get(condition)
        if not m:
            out.append(f"| `{condition}` | {NA} | - | - |")
            continue
        ood_rate = (
            f"**{m.ood_escalation_rate:.1%}** "
            f"({m.count(m.ood, 'ESCALATED')}/{len(m.ood)})"
            if m.ood_escalation_rate is not None else "n/a"
        )
        out.append(
            f"| `{condition}` | {ood_rate} | "
            f"{pct(m.escalated_in_dist, m.n_in_dist)} "
            f"({m.escalated_in_dist}/{m.n_in_dist}) | "
            f"{m.count(m.ood, 'OOD_ANSWERED_PLAUSIBLE')} / "
            f"{m.count(m.ood, 'OOD_ANSWERED_WRONG')} |"
        )

    out += [
        "",
        "> `OOD_ANSWERED_PLAUSIBLE` is not a success. The system was asked to "
        "escalate what it cannot ground and instead answered from parametric "
        "knowledge, happening to be right. It is separated from "
        "`OOD_ANSWERED_WRONG` because a confidently wrong answer on an unknown "
        "failure and an unguarded correct one are different behaviours.",
        "",
        "> Under `rag_off` there is no retrieval signal to threshold, so the OOD "
        "floor cannot function by construction. Its OOD row measures what the "
        "system does with an unknown failure when it has no grounding and no way "
        "to escalate - which is the direct evidence for why the floor exists.",
        "",
    ]
    return out


def section_latency(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = [
        "## 4. Latency",
        "",
        "Total wall time per `/diagnose` request as measured by the harness. "
        "`/diagnose` returns no per-stage timings, so this is the end-to-end "
        "figure, not a breakdown: it covers embedding, retrieval, the LLM call, "
        "schema validation and the SQLite insert together.",
        "",
        "| Condition | p50 | p95 | max | n | vs 60s target |",
        "|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        m = by_condition.get(condition)
        values = m.latencies() if m else []
        if not values:
            out.append(f"| `{condition}` | {NA} | - | - | 0 | - |")
            continue
        p50, p95, mx = percentile(values, 0.50), percentile(values, 0.95), max(values)
        verdict = "within" if mx < 60_000 else "**EXCEEDS**"
        out.append(
            f"| `{condition}` | {p50 / 1000:.2f}s | {p95 / 1000:.2f}s | "
            f"{mx / 1000:.2f}s | {len(values)} | {verdict} |"
        )

    out += [
        "",
        "> Local stack only: `sentence-transformers` embedding, ChromaDB over "
        "loopback, and the hosted Gemini API. The cloud path (Vertex AI embeddings, "
        "Firestore, Cloud Run cold start) is not represented here and "
        "budgets a further 100-300 ms for the cross-cloud hop.",
        "",
        "> p95 at this n is the 2nd-slowest observation. It is a description of "
        "these runs, not an estimate of a population quantile.",
        "",
    ]
    return out


def section_schema(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = [
        "## 5. JSON schema compliance",
        "",
        "Fraction of generations that satisfied the `Diagnosis` schema on the "
        "**first** attempt, before the retry-once fallback. Requests that never "
        "reached the model (OOD escalations) are excluded from the denominator.",
        "",
        "| Condition | First-try compliance | n (generations) |",
        "|---|---|---|",
    ]
    any_data = False
    for condition in CONDITIONS:
        m = by_condition.get(condition)
        if not m:
            out.append(f"| `{condition}` | {NA} | 0 |")
            continue
        ok, total = m.schema_compliance()
        any_data = any_data or total > 0
        out.append(
            f"| `{condition}` | {pct(ok, total)} ({ok}/{total}) | {total} |"
            if total else f"| `{condition}` | {NA} | 0 |"
        )

    out.append("")
    if not any_data:
        out += [
            "**Not computable from the current logs.** A first-attempt failure that "
            "the retry recovered leaves no trace: `main.py` logs the retry prompt and "
            "reports `schema_failure=False` when the retry succeeds. The grader infers "
            "retries by detecting the retry instruction inside the logged prompt; an "
            "explicit `schema_retry` boolean on the log record would be more robust.",
            "",
        ]
    return out


def section_citations(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    out = ["## 6. Citation validity", ""]
    m = by_condition.get("rag_on")
    rates = m.citation_rates() if m else []

    if not rates:
        out += [
            f"**{NA}.** Requires the per-response valid/invalid citation counts, "
            "which the RAG engine does not yet record on its log entries.",
            "",
            "This metric puts a number on admission that grounding "
            "*reduces but does not eliminate* hallucination. The known instance from "
            "Phase 1c - the model citing `\"Worked example (Pharos simulator):\"`, a "
            "sub-heading lifted from inside a chunk body rather than a real chunk id "
            "- is exactly what it measures.",
            "",
        ]
        return out

    out += [
        f"- **Mean citation validity: {statistics.mean(rates):.1%}** "
        f"(n={len(rates)} in-distribution `rag_on` responses that cited anything)",
        f"- Responses with at least one fabricated citation: "
        f"{pct(sum(1 for r in rates if r < 1.0), len(rates))}",
        "",
        "> A citation is valid only if it exactly equals a chunk id the retriever "
        "actually returned. Anything below 100% is a measured instance of "
        "hallucination caveat, not a rounding artefact.",
        "",
        "> `rag_off` is excluded: with no chunks retrieved, every citation is "
        "invalid by construction, so a 0% there would measure the experimental "
        "setup rather than the model. Any citation produced under `rag_off` is "
        "counted as a fabricated citation instead.",
        "",
    ]
    return out


def section_scatter(rows: list[dict], write_files: bool) -> list[str]:
    points = []
    for row in rows:
        if row["condition"] != "rag_on":
            continue
        score = as_float(row["retrieval_relevance_score"])
        if score is None or row["grade"] in ("ERROR", "NEEDS_HUMAN"):
            continue
        points.append((row["incident_id"], row["condition"], score, row["grade"],
                       as_bool(row["is_ood"])))

    out = ["## 7. Retrieval relevance vs. correctness", ""]
    if not points:
        out += [f"**{NA}** - no graded rows carry a relevance score.", ""]
        return out

    if write_files:
        SCATTER_CSV.parent.mkdir(parents=True, exist_ok=True)
        with SCATTER_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["incident_id", "condition", "relevance_score", "grade", "is_ood"])
            w.writerows(points)

    scored = [(s, g) for _, _, s, g, ood in points if not ood]
    successes = [s for s, g in scored if g in SUCCESS_GRADES]
    failures = [s for s, g in scored if g not in SUCCESS_GRADES]

    out += [
        f"Scatter data: `{SCATTER_CSV.relative_to(REPO_ROOT)}` "
        f"({len(points)} graded `rag_on` points).",
        "",
        "`rag_off` is excluded entirely: with no retriever its score is 0.0 for "
        "every incident, so including it would place the whole baseline at zero "
        "and produce a separation that reflects the experimental condition rather "
        "than any relationship being tested.",
        "",
    ]
    if successes and failures:
        out += [
            f"- Mean relevance where the diagnosis succeeded: "
            f"**{statistics.mean(successes):.3f}** (n={len(successes)})",
            f"- Mean relevance where it did not: "
            f"**{statistics.mean(failures):.3f}** (n={len(failures)})",
            f"- Separation: {statistics.mean(successes) - statistics.mean(failures):+.3f}",
            "",
        ]
    else:
        present = "successes" if successes else "failures"
        out += [
            f"- Only {present} present among in-distribution graded rows "
            f"(n={len(scored)}), so no separation can be computed.",
            "",
        ]

    out += [
        "> **This is a sanity check, not a calibration.** The retrieval-relevance "
        "score measures similarity to known patterns, never diagnosis correctness "
        ". A weak or absent separation is a valid finding that "
        "reinforces that rule; it is reported as observed and nothing is gated on it.",
        "",
        f"> n={len(scored)} in-distribution points. No correlation coefficient is "
        "quoted: at this n it would be dominated by individual observations.",
        "",
    ]

    if write_files:
        out += plot_scatter(points)
    return out


def plot_scatter(points: list[tuple]) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return [
            "> Plot not generated: `matplotlib` is not installed. The scatter CSV "
            "above contains the data. Install with `.venv/bin/pip install matplotlib` "
            "and re-run to produce the figure.",
            "",
        ]

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOTS_DIR / "relevance_vs_correctness.png"

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label, keep, colour, marker in (
        ("success (in-dist)", lambda g, o: not o and g in SUCCESS_GRADES, "#2a9d8f", "o"),
        ("failure (in-dist)", lambda g, o: not o and g not in SUCCESS_GRADES, "#e76f51", "X"),
        ("OOD", lambda g, o: o, "#6c757d", "^"),
    ):
        xs = [s for _, _, s, g, o in points if keep(g, o)]
        ys = [i for i, (_, _, s, g, o) in enumerate(points) if keep(g, o)]
        if xs:
            ax.scatter(xs, ys, label=f"{label} (n={len(xs)})", c=colour,
                       marker=marker, alpha=0.8, s=45)

    ax.set_xlabel("retrieval-relevance score (similarity to known patterns, NOT confidence)")
    ax.set_ylabel("incident (arbitrary order)")
    ax.set_title("Retrieval relevance vs. diagnosis outcome")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)

    return [f"Plot: `{path.relative_to(REPO_ROOT)}`", ""]


def section_memory_demo(path: Path) -> list[str]:
    out = ["## 8. Incident Memory demo", ""]
    if not path.exists():
        out += [
            f"**{NA}** - `{path.name}` not found. Run the memory demo "
            "(`validation/harness/memory_demo.py`) to produce it.",
            "",
            "The demo is deliberately a separate procedure rather than part of this "
            "module: it mutates the corpus by memorising incidents, so folding it "
            "into metrics.py would make the report impossible to recompute without "
            "changing the thing being measured.",
            "",
        ]
        return out

    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data.get("runs", [])
    passed = [r for r in runs if r.get("passed")]
    deltas = [r["second_score"] - r["first_score"] for r in runs
              if r.get("first_score") is not None and r.get("second_score") is not None]

    out += [
        f"- **Runs passed: {len(passed)}/{len(runs)}** - the second diagnosis of an "
        "identical incident context cites the memorised chunk from the first.",
        "",
    ]
    if deltas:
        out += [
            f"- **Mean relevance increase: {statistics.mean(deltas):+.3f}** "
            f"(n={len(deltas)} paired runs)",
            f"- Range: {min(deltas):+.3f} to {max(deltas):+.3f}",
            "",
        ]
    out += [
        "> This is headline differentiator measured rather than "
        "asserted: the corpus learns from a resolved incident, and the next "
        "occurrence retrieves it. Paired design - each run compares the same "
        "context against itself before and after memorisation.",
        "",
    ]
    return out


def section_provenance(rows: list[dict], by_condition: dict[str, ConditionMetrics],
                       grades_path: Path) -> list[str]:
    human = [r for r in rows if r.get("graded_by") == "human"]
    pending = [r for r in rows if r["grade"] == "NEEDS_HUMAN"]
    share = 100 * len(pending) / len(rows) if rows else 0

    out = [
        "## 9. Grading provenance",
        "",
        f"- Rows graded: **{len(rows)}** from `{grades_path.name}`",
        f"- Resolved mechanically by rubric: **{len(rows) - len(human)}**",
        f"- Resolved by a human: **{len(human)}**",
        f"- Still `NEEDS_HUMAN`: **{len(pending)}** ({share:.0f}%)",
        "",
    ]
    if pending:
        out += [
            f"> **{len(pending)} row(s) remain ungraded.** Every figure above treats "
            "them as non-successes, so the success rates are lower bounds until the "
            "manual pass is complete.",
            "",
        ]
    if share >= 20:
        out += [
            f"> **{share:.0f}% of rows required human judgement** (the rubric threshold "
            "is 20%). The headline numbers are therefore partly a human judgement "
            "call, not purely mechanical. Stated here rather than buried.",
            "",
        ]
    if human:
        out += ["Manual grades and their stated reasons:", ""]
        for row in human:
            note = row.get("human_note") or "(no reason recorded)"
            out.append(f"- `{row['incident_id']}` / `{row['condition']}` -> "
                       f"**{row['grade']}** - {note}")
        out.append("")
    return out


def section_caveats(by_condition: dict[str, ConditionMetrics]) -> list[str]:
    n = next((m.n_in_dist for m in by_condition.values() if m.n_in_dist), 15)
    return [
        "## 10. Limitations",
        "",
        f"1. **Small N.** {n} in-distribution and 15 OOD incidents per condition. "
        f"One incident is worth {100 / n:.1f} percentage points. All figures are "
        "indicative; no significance is claimed anywhere in this report.",
        "2. **Synthetic incidents.** The dataset is generated, not harvested from a "
        "live cluster. Evidence shape matches what the watcher gathers, but real "
        "incidents are noisier and more ambiguous than these.",
        "3. **Lexical overlap.** Kubernetes event strings such as "
        "`Back-off restarting failed container` appear verbatim in "
        "`crashloop-backoff.md`. They are the literal strings the kubelet emits, so "
        "removing them would make the dataset unrealistic - but they give crashloop "
        "retrieval a small boost over a purely semantic match.",
        "4. **Relevance is not confidence.** Section 7 is an honest check on the "
        "escalation threshold, never a calibration claim.",
        "5. **Single model family.** One embedding model, one LLM, greedy decoding - "
        "near-deterministic, not fully deterministic. Results are not portable to "
        "other model families.",
        "6. **Rubric-bound grading.** Success is defined by the keyword rules in "
        "`validation/dataset/rubric.md`, frozen before the harness first ran. A "
        "correct diagnosis worded outside those lists is graded `NEEDS_HUMAN`, not "
        "wrong - but the rubric's coverage still bounds what the numbers can mean.",
        "",
    ]


def build_report(rows: list[dict], labels: dict[str, dict], args) -> str:
    by_condition = {
        c: ConditionMetrics(c, [r for r in rows if r["condition"] == c])
        for c in CONDITIONS
        if any(r["condition"] == c for r in rows)
    }

    lines = [
        "# Pharos - Phase 1f Validation Report",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`validation/harness/metrics.py`. Regenerate with "
        "`python validation/harness/metrics.py`.",
        "",
        "Local stack, $0. Two conditions differing in exactly one thing: `rag_on` "
        "runs the full retrieval pipeline, `rag_off` runs the same pipeline with a "
        "no-op retriever. Same dataset, same model, same temperature, same prompt "
        "template minus the retrieved chunks.",
        "",
        "Grades come from `validation/dataset/rubric.md`, committed before the "
        "harness first ran. Every number below states its n.",
        "",
        "---",
        "",
    ]

    lines += section_headline(by_condition)
    lines += ["---", ""]
    lines += section_success(by_condition)
    lines += section_retrieval(by_condition, labels)
    lines += section_ood(by_condition)
    lines += section_latency(by_condition)
    lines += section_schema(by_condition)
    lines += section_citations(by_condition)
    lines += section_scatter(rows, write_files=not args.no_files)
    lines += section_memory_demo(args.memory_demo)
    lines += ["---", ""]
    lines += section_provenance(rows, by_condition, args.grades)
    lines += section_caveats(by_condition)

    return "\n".join(lines) + "\n"


def console_summary(rows: list[dict]) -> None:
    by_condition = {
        c: ConditionMetrics(c, [r for r in rows if r["condition"] == c])
        for c in CONDITIONS
        if any(r["condition"] == c for r in rows)
    }
    print("\ntop-line numbers")
    for condition in CONDITIONS:
        m = by_condition.get(condition)
        if not m:
            print(f"  {condition:<9} {NA}")
            continue
        rate = f"{m.primary_success_rate:.1%}" if m.primary_success_rate is not None else "n/a"
        ood = f"{m.ood_escalation_rate:.1%}" if m.ood_escalation_rate is not None else "n/a"
        print(f"  {condition:<9} success={rate:<7} (n={m.n_in_dist})   "
              f"ood_escalation={ood:<7} needs_human={m.pending_human}")

    on, off = by_condition.get("rag_on"), by_condition.get("rag_off")
    if on and off and on.primary_success_rate is not None and off.primary_success_rate is not None:
        print(f"\n  DELTA (rag_on - rag_off) = "
              f"{on.primary_success_rate - off.primary_success_rate:+.1%}")
    else:
        print(f"\n  DELTA = {NA} - both conditions must be graded")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grades", type=Path, default=DEFAULT_GRADES)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--memory-demo", type=Path, default=DEFAULT_MEMORY_DEMO)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--no-files", action="store_true",
                    help="skip the scatter CSV and plot; write the report only")
    args = ap.parse_args()

    if not args.grades.exists():
        sys.exit(f"grades not found: {args.grades}\nRun validation/harness/grade.py first.")

    with args.grades.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{args.grades} has no rows")

    labels = {
        json.loads(line)["id"]: json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    report = build_report(rows, labels, args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8", newline="\n")

    print(f"wrote {args.report}")
    console_summary(rows)


if __name__ == "__main__":
    main()
