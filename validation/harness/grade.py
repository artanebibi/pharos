#!/usr/bin/env python3
"""Apply validation/dataset/rubric.md to the harness results and emit grades.csv."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC = REPO_ROOT / "validation" / "dataset" / "rubric.md"
DEFAULT_DATASET = REPO_ROOT / "validation" / "dataset" / "incidents.jsonl"
RESULTS_DIR = REPO_ROOT / "validation" / "results"
DEFAULT_OUTPUT = RESULTS_DIR / "grades.csv"
DEFAULT_ENGINE_LOG = REPO_ROOT / "tests" / "logs" / "diagnose_log.jsonl"

CONDITIONS = ("rag_on", "rag_off")

ESCALATION_ROOT_CAUSE = "unknown failure mode"  # normalized form of the constant

COLUMNS = [
    "incident_id", "condition", "grade", "graded_by", "rule",
    "root_cause_matched", "remediation_matched", "retrieval_relevance_score",
    "first_try_schema_ok", "citation_validity_rate",
    "retrieved_correct_runbook", "retrieved_chunk_ids",
    "latency_ms", "is_ood", "failure_type",
    "expected_root_cause_category", "root_cause", "human_note",
]

_RETRY_MARKER_FALLBACK = "YOUR PREVIOUS RESPONSE FAILED SCHEMA VALIDATION"


def _retry_marker() -> str:
    engine = REPO_ROOT / "services" / "rag-engine"
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    try:
        from prompts import SCHEMA_RETRY_INSTRUCTION  # type: ignore
        return SCHEMA_RETRY_INSTRUCTION.strip().splitlines()[0]
    except Exception:
        return _RETRY_MARKER_FALLBACK


RETRY_MARKER = _retry_marker()


_STRIP = str.maketrans({"-": " ", "_": " ", "/": " ", "`": " ", "*": "", "#": ""})


def normalize(text: str) -> str:
    return " ".join(text.lower().translate(_STRIP).split())


def matches(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


def which(text: str, table: dict[str, list[str]], keys) -> list[str]:
    return [k for k in keys if matches(text, table[k])]


@dataclass
class Rubric:
    categories_by_type: dict[str, list[str]] = field(default_factory=dict)
    runbook_by_type: dict[str, str] = field(default_factory=dict)
    specific: dict[str, list[str]] = field(default_factory=dict)
    generic: dict[str, list[str]] = field(default_factory=dict)
    exclusive: dict[str, list[str]] = field(default_factory=dict)
    ood: dict[str, list[str]] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    artifacts: dict[str, list[str]] = field(default_factory=dict)


def _backticked(cell: str) -> list[str]:
    return [m.strip() for m in re.findall(r"`([^`]+)`", cell)]


def _find_anchor(lines: list[str], anchor: str) -> int:
    for i, line in enumerate(lines):
        if anchor in line:
            return i
    sys.exit(f"rubric: anchor {anchor!r} not found in the rubric - cannot grade")


def _table_after(lines: list[str], anchor: str) -> list[list[str]]:
    i = _find_anchor(lines, anchor)
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        i += 1
    rows: list[list[str]] = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(set(c) <= set("-: ") for c in cells):  # skip the |---|---| rule
            rows.append(cells)
        i += 1
    if len(rows) < 2:
        sys.exit(f"rubric: no table found after anchor {anchor!r}")
    return rows[1:]  # drop the header row


def _marker_table(lines: list[str], anchor: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cells in _table_after(lines, anchor):
        key = _backticked(cells[0])
        if not key:
            sys.exit(f"rubric: row under {anchor!r} has no backticked key: {cells[0]!r}")
        out[key[0]] = [normalize(m) for m in _backticked(cells[1])]
    return out


def _paragraph_after(lines: list[str], anchor: str) -> str:
    i = _find_anchor(lines, anchor)
    chunk: list[str] = []
    while i < len(lines) and lines[i].strip():
        chunk.append(lines[i])
        i += 1
    return " ".join(chunk)


def parse_rubric(path: Path) -> Rubric:
    if not path.exists():
        sys.exit(f"rubric not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()

    rubric = Rubric()

    for cells in _table_after(lines, "## 3. Labels"):
        failure_type = _backticked(cells[0])[0]
        rubric.categories_by_type[failure_type] = _backticked(cells[1])
        rubric.runbook_by_type[failure_type] = _backticked(cells[2])[0]

    rubric.specific = _marker_table(lines, "**Category-specific**")
    rubric.generic = _marker_table(lines, "**Failure-type generic**")
    rubric.exclusive = _marker_table(lines, "**Failure-type exclusive**")
    rubric.ood = _marker_table(lines, "**OOD categories:**")
    rubric.artifacts = _marker_table(lines, "| Category | ARTIFACT |")
    rubric.actions = [normalize(a) for a in _backticked(
        _paragraph_after(lines, "**ACTION (shared):**")
    )]

    check_rubric(rubric)
    return rubric


def check_rubric(r: Rubric) -> None:
    problems: list[str] = []
    expected_categories = {c for cats in r.categories_by_type.values() for c in cats}

    if len(r.categories_by_type) != 3:
        problems.append(f"expected 3 in-distribution failure types, parsed {len(r.categories_by_type)}")
    if len(expected_categories) != 8:
        problems.append(f"expected 8 root-cause categories, parsed {len(expected_categories)}")
    if set(r.specific) != expected_categories:
        problems.append(
            " category-specific markers do not cover exactly the  categories: "
            f"missing={sorted(expected_categories - set(r.specific))} "
            f"extra={sorted(set(r.specific) - expected_categories)}"
        )
    if set(r.artifacts) != expected_categories:
        problems.append(
            " ARTIFACT rows do not cover exactly the  categories: "
            f"missing={sorted(expected_categories - set(r.artifacts))} "
            f"extra={sorted(set(r.artifacts) - expected_categories)}"
        )
    if set(r.generic) != set(r.categories_by_type):
        problems.append
    if set(r.exclusive) != set(r.categories_by_type):
        problems.append
    if len(r.ood) != 5:
        problems.append(f"expected 5 OOD categories, parsed {len(r.ood)}")
    if not r.actions:
        problems.append
    for name, table in (("specific", r.specific), ("generic", r.generic),
                        ("exclusive", r.exclusive), ("ood", r.ood),
                        ("artifacts", r.artifacts)):
        for key, markers in table.items():
            if not markers:
                problems.append

    if problems:
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        sys.exit(
            "grade.py: the rubric did not parse into the expected shape. Grading "
            "aborted rather than falling back to assumptions."
        )


@dataclass
class Verdict:
    grade: str
    rule: str
    root_cause_matched: bool
    remediation_matched: bool


def grade_in_distribution(r: Rubric, result: dict, expected_category: str,
                          failure_type: str) -> Verdict:
    if not result.get("ok"):
        return Verdict("ERROR", "R0", False, False)

    diagnosis = result["diagnosis"] or {}
    rc = normalize(str(diagnosis.get("root_cause", "")))
    remediation = normalize(" ".join(
        list(diagnosis.get("remediation_steps") or [])
        + list(diagnosis.get("kubectl_commands") or [])
    ))

    rem_matched = (
        matches(remediation, r.actions)
        and matches(remediation, r.artifacts[expected_category])
    )

    if rc == ESCALATION_ROOT_CAUSE:
        return Verdict("ESCALATED", "R1", False, rem_matched)

    same_type = r.categories_by_type[failure_type]
    hit = which(rc, r.specific, same_type)

    if len(hit) >= 2:
        return Verdict("NEEDS_HUMAN", "R2", True, rem_matched)

    if expected_category in hit:
        return Verdict(
            "CORRECT" if rem_matched else "PARTIALLY_CORRECT", "R3", True, rem_matched
        )

    if len(hit) == 1:  # right failure mode, wrong specific cause
        return Verdict("PARTIALLY_CORRECT", "R4", False, rem_matched)

    other_types = [t for t in r.exclusive if t != failure_type]
    conflicts = which(rc, r.exclusive, other_types)

    if matches(rc, r.generic[failure_type]):
        if conflicts:
            return Verdict("NEEDS_HUMAN", "R5", False, rem_matched)
        return Verdict("PARTIALLY_CORRECT", "R5", False, rem_matched)

    if len(conflicts) == 1:
        return Verdict("INCORRECT", "R6", False, rem_matched)

    return Verdict("NEEDS_HUMAN", "R7", False, rem_matched)


def grade_ood(r: Rubric, result: dict, expected_category: str) -> Verdict:
    if not result.get("ok"):
        return Verdict("ERROR", "O0", False, False)

    diagnosis = result["diagnosis"] or {}
    rc = normalize(str(diagnosis.get("root_cause", "")))

    if rc == ESCALATION_ROOT_CAUSE:
        return Verdict("ESCALATED", "O1", False, False)

    hit = which(rc, r.ood, list(r.ood))
    if len(hit) >= 2:
        return Verdict("NEEDS_HUMAN", "O2", True, False)
    if expected_category in hit:
        return Verdict("OOD_ANSWERED_PLAUSIBLE", "O3", True, False)
    return Verdict("OOD_ANSWERED_WRONG", "O4", False, False)


def load_engine_log(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    index: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        incident_id = (record.get("diagnosis") or {}).get("incident_id")
        if incident_id:
            index[incident_id] = record
    return index


def schema_column(log_record: dict | None) -> str:
    if not log_record:
        return ""
    if log_record.get("schema_failure"):
        return "False"  # failed twice, request 500'd
    prompt = log_record.get("prompt")
    if prompt is None:
        return ""  # no LLM call: OOD escalation, or a generation failure
    return str(RETRY_MARKER not in prompt)


def retrieval_columns(
    log_record: dict | None, expected_runbook: str | None
) -> tuple[str, str, str]:
    if not log_record:
        return "", "", ""

    rate = log_record.get("citation_validity_rate", "MISSING")
    rate_cell = "" if rate == "MISSING" else ("" if rate is None else f"{float(rate):.3f}")

    chunk_ids = log_record.get("retrieved_chunk_ids")
    if chunk_ids is None:
        return rate_cell, "", ""

    ids_cell = ";".join(str(c) for c in chunk_ids)
    if expected_runbook is None:  # OOD incidents have no expected runbook
        return rate_cell, "", ids_cell

    hit = any(str(cid).split("::", 1)[0] == expected_runbook for cid in chunk_ids)
    return rate_cell, str(hit), ids_cell


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_existing_grades(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {(row["incident_id"], row["condition"]): row for row in csv.DictReader(f)}


def blind_sort_key(incident_id: str, condition: str) -> str:
    return hashlib.sha256(f"{incident_id}|{condition}".encode()).hexdigest()


def build_rows(args: argparse.Namespace, rubric: Rubric) -> list[dict]:
    labels = {inc["id"]: inc for inc in load_jsonl(args.dataset)}
    engine_log = load_engine_log(args.engine_log)
    existing = load_existing_grades(args.output)

    conditions = [args.condition] if args.condition else list(CONDITIONS)
    rows: list[dict] = []

    results_dir = args.results_dir or RESULTS_DIR
    for condition in conditions:
        results_path = results_dir / f"{condition}.jsonl"
        if not results_path.exists():
            print(f"  - {condition}: no results file yet ({results_path.name}) - skipped")
            continue

        collapsed: dict[str, dict] = {}
        for result in load_jsonl(results_path):
            collapsed[result["id"]] = result

        for result in collapsed.values():
            incident_id = result["id"]
            label = labels.get(incident_id)
            if label is None:
                sys.exit(f"{condition}: result {incident_id!r} is not in the dataset")

            if label["is_ood"]:
                verdict = grade_ood(rubric, result, label["expected_root_cause_category"])
            else:
                verdict = grade_in_distribution(
                    rubric, result,
                    label["expected_root_cause_category"],
                    label["failure_type"],
                )

            log_record = engine_log.get(result.get("incident_id") or "")
            rate_cell, retrieved_cell, chunk_ids_cell = retrieval_columns(
                log_record, label["expected_runbook"]
            )

            grade, graded_by, note = verdict.grade, "auto", ""
            prior = existing.get((incident_id, condition))
            if prior and prior.get("graded_by") == "human":
                grade, graded_by, note = prior["grade"], "human", prior.get("human_note", "")

            diagnosis = result.get("diagnosis") or {}
            rows.append({
                "incident_id": incident_id,
                "condition": condition,
                "grade": grade,
                "graded_by": graded_by,
                "rule": verdict.rule,
                "root_cause_matched": str(verdict.root_cause_matched),
                "remediation_matched": str(verdict.remediation_matched),
                "retrieval_relevance_score": diagnosis.get("retrieval_relevance_score", ""),
                "first_try_schema_ok": schema_column(log_record),
                "citation_validity_rate": rate_cell,
                "retrieved_correct_runbook": retrieved_cell,
                "retrieved_chunk_ids": chunk_ids_cell,
                "latency_ms": result.get("wall_ms", ""),
                "is_ood": str(label["is_ood"]),
                "failure_type": label["failure_type"],
                "expected_root_cause_category": label["expected_root_cause_category"],
                "root_cause": str(diagnosis.get("root_cause", "")),
                "human_note": note,
            })

    rows.sort(key=lambda r: blind_sort_key(r["incident_id"], r["condition"]))
    return rows


def report(rows: list[dict]) -> None:
    if not rows:
        print("\nno rows graded - run the harness first")
        return

    conditions = sorted({r["condition"] for r in rows})
    grades = sorted({r["grade"] for r in rows})

    width = max(len(g) for g in grades) + 2
    print("\ngrade distribution")
    print(f"  {'':<{width}}" + "".join(f"{c:>10}" for c in conditions))
    for grade in grades:
        counts = [sum(1 for r in rows if r["grade"] == grade and r["condition"] == c)
                  for c in conditions]
        print(f"  {grade:<{width}}" + "".join(f"{n:>10}" for n in counts))

    print("\nNEEDS_HUMAN - manual grading required")
    total_pending = 0
    for condition in conditions:
        pending = [r for r in rows
                   if r["grade"] == "NEEDS_HUMAN" and r["condition"] == condition]
        total_pending += len(pending)
        graded = [r for r in rows if r["condition"] == condition]
        share = 100 * len(pending) / len(graded) if graded else 0
        print(f"  {condition:<10} {len(pending):>3} of {len(graded):<3} ({share:.0f}%)")
        for row in pending:
            print(f"       {row['incident_id']:<22} rule={row['rule']:<3} "
                  f"{row['root_cause'][:56]}")

    if total_pending:
        print(
            f"\n  >>> {total_pending} row(s) need manual grading. Edit grades.csv: set\n"
            f"      `grade` to the resolved value, `graded_by` to human, and write a\n"
            f"      one-line `human_note`. Re-running grade.py preserves them.\n"
            f"      Grade WITHOUT looking at the condition column."
        )
        share = 100 * total_pending / len(rows)
        if share >= 20:
            print(
                f"  >>> {share:.0f}% of all rows are NEEDS_HUMAN. the rubric requires this\n"
                f"      to be stated in report.md - the headline numbers are then\n"
                f"      partly human judgement and that must be visible."
            )
    else:
        print("\n  no manual grading required")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--engine-log", type=Path, default=DEFAULT_ENGINE_LOG)
    ap.add_argument("--results-dir", type=Path, default=None,
                    help="directory holding {condition}.jsonl (default: validation/results)")
    ap.add_argument("--condition", choices=CONDITIONS, default=None,
                    help="grade one condition only (default: both, if present)")
    args = ap.parse_args()

    rubric = parse_rubric(args.rubric)
    print(
        f"rubric: {len(rubric.specific)} categories, {len(rubric.ood)} OOD categories, "
        f"{len(rubric.actions)} action verbs parsed from {args.rubric.name}"
    )

    rows = build_rows(args, rubric)
    if not rows:
        report(rows)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {args.output} ({len(rows)} rows)")
    report(rows)


if __name__ == "__main__":
    main()
