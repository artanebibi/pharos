# Pharos - Phase 1f Validation Report

Generated 2026-08-16 07:06 UTC by `validation/harness/metrics.py`. Regenerate with `python validation/harness/metrics.py`.

Local stack, $0. Two conditions differing in exactly one thing: `rag_on` runs the full retrieval pipeline, `rag_off` runs the same pipeline with a no-op retriever. Same dataset, same model, same temperature, same prompt template minus the retrieved chunks.

Grades come from `validation/dataset/rubric.md`, committed before the harness first ran. Every number below states its n.

---

## The headline: does retrieval help?

**Retrieval on: 93.3%  retrieval off: 93.3%  delta: +0.0%**  (n=15 in-distribution incidents per condition)

End-to-end success is identical with retrieval enabled. The two runs used the same dataset, the same model at the same temperature, and the same prompt template minus the retrieved chunks - retrieval is the only variable that differs, which is what makes this delta attributable to it.

> **n=15 per condition.** With a dataset this size a single incident moves the rate by 6.7 percentage points. The delta indicates a direction, not an effect size, and no confidence interval is claimed.

> The delta is not positive. Per docs/phase-1f.md this is reported as found rather than adjusted - but it is also a signal worth investigating in the corpus, the chunking, or the embedding before the result is written up as a property of RAG in general.

---

## 1. End-to-end success rate

In-distribution incidents only. Success = CORRECT or PARTIALLY_CORRECT.

| Condition | Primary success | Strict (CORRECT only) | Conditional accuracy | Escalated | Errors | n |
|---|---|---|---|---|---|---|
| `rag_on` | **93.3%** (14/15) | 73.3% | 100.0% (n=14) | 0 | 1 | 15 |
| `rag_off` | **93.3%** (14/15) | 60.0% | 100.0% (n=14) | 0 | 1 | 15 |

**Primary** keeps escalations and errors in the denominator; **conditional** removes them and is reported with its own n. Both appear because they can differ sharply: on the conditional convention alone, a system that escalated 14 of 15 incidents and got the last one right would report 100%.

## 2. Retrieval quality (Precision@5, MRR)

Against the labelled incident->runbook mapping, `rag_on` only, n=14 in-distribution incidents.

- **Precision@5: 0.471** (ceiling 0.80)
- **MRR: 0.869**
- Correct runbook retrieved at all: 100.0%

> **The Precision@5 ceiling is 0.80, not 1.0.** Each runbook contributes exactly 4 chunks to the corpus (Symptom / Root Causes / Diagnosis Steps / Remediation), so at most 4 of 5 retrieved slots can belong to the expected runbook. A perfect retriever scores 0.80 here. Read the figure against that ceiling, not against 1.0.

> Incident-memory chunks in the corpus at run time count as non-matching: they are not runbook chunks and cannot satisfy `expected_runbook`.

## 3. Out-of-distribution behaviour

The OOD floor's job is to escalate what the corpus cannot ground . Both sides of that trade are reported: what it catches, and what it wrongly rejects.

| Condition | OOD escalation rate | False escalation (in-dist) | Answered anyway: plausible / wrong |
|---|---|---|---|
| `rag_on` | n/a | 0.0% (0/15) | 0 / 0 |
| `rag_off` | n/a | 0.0% (0/15) | 0 / 0 |

> `OOD_ANSWERED_PLAUSIBLE` is not a success. The system was asked to escalate what it cannot ground and instead answered from parametric knowledge, happening to be right. It is separated from `OOD_ANSWERED_WRONG` because a confidently wrong answer on an unknown failure and an unguarded correct one are different behaviours.

> Under `rag_off` there is no retrieval signal to threshold, so the OOD floor cannot function by construction. Its OOD row measures what the system does with an unknown failure when it has no grounding and no way to escalate - which is the direct evidence for why the floor exists.

## 4. Latency

Total wall time per `/diagnose` request as measured by the harness. `/diagnose` returns no per-stage timings, so this is the end-to-end figure, not a breakdown: it covers embedding, retrieval, the LLM call, schema validation and the SQLite insert together.

| Condition | p50 | p95 | max | n | vs 60s target |
|---|---|---|---|---|---|
| `rag_on` | 10.08s | 22.87s | 22.87s | 15 | within |
| `rag_off` | 6.80s | 20.32s | 20.32s | 15 | within |

> Local stack only: `sentence-transformers` embedding, ChromaDB over loopback, and the hosted Gemini API. The cloud path (Vertex AI embeddings, Firestore, Cloud Run cold start) is not represented here and budgets a further 100-300 ms for the cross-cloud hop.

> p95 at this n is the 2nd-slowest observation. It is a description of these runs, not an estimate of a population quantile.

## 5. JSON schema compliance

Fraction of generations that satisfied the `Diagnosis` schema on the **first** attempt, before the retry-once fallback. Requests that never reached the model (OOD escalations) are excluded from the denominator.

| Condition | First-try compliance | n (generations) |
|---|---|---|
| `rag_on` | 78.6% (11/14) | 14 |
| `rag_off` | 85.7% (12/14) | 14 |

## 6. Citation validity

- **Mean citation validity: 100.0%** (n=14 in-distribution `rag_on` responses that cited anything)
- Responses with at least one fabricated citation: 0.0%

> A citation is valid only if it exactly equals a chunk id the retriever actually returned. Anything below 100% is a measured instance of hallucination caveat, not a rounding artefact.

> `rag_off` is excluded: with no chunks retrieved, every citation is invalid by construction, so a 0% there would measure the experimental setup rather than the model. Any citation produced under `rag_off` is counted as a fabricated citation instead.

## 7. Retrieval relevance vs. correctness

Scatter data: `validation/results/relevance_vs_correctness.csv` (14 graded `rag_on` points).

`rag_off` is excluded entirely: with no retriever its score is 0.0 for every incident, so including it would place the whole baseline at zero and produce a separation that reflects the experimental condition rather than any relationship being tested.

- Only successes present among in-distribution graded rows (n=14), so no separation can be computed.

> **This is a sanity check, not a calibration.** The retrieval-relevance score measures similarity to known patterns, never diagnosis correctness . A weak or absent separation is a valid finding that reinforces that rule; it is reported as observed and nothing is gated on it.

> n=14 in-distribution points. No correlation coefficient is quoted: at this n it would be dominated by individual observations.

> Plot not generated: `matplotlib` is not installed. The scatter CSV above contains the data. Install with `.venv/bin/pip install matplotlib` and re-run to produce the figure.

## 8. Incident Memory demo

**not available** - `memory_demo.json` not found. Run the memory demo (`validation/harness/memory_demo.py`) to produce it.

The demo is deliberately a separate procedure rather than part of this module: it mutates the corpus by memorising incidents, so folding it into metrics.py would make the report impossible to recompute without changing the thing being measured.

---

## 9. Grading provenance

- Rows graded: **30** from `grades.csv`
- Resolved mechanically by rubric: **27**
- Resolved by a human: **3**
- Still `NEEDS_HUMAN`: **0** (0%)

Manual grades and their stated reasons:

- `inc-h-oom-003` / `rag_on` -> **CORRECT** - names the leak as the cause; the memory limit is cited as its consequence, not a rival explanation
- `inc-h-oom-003` / `rag_off` -> **PARTIALLY_CORRECT** - offers leak OR undersized limit without committing; right failure mode but not a decided diagnosis
- `inc-h-oom-005` / `rag_off` -> **PARTIALLY_CORRECT** - spots GC thrashing but blames the container limit rather than the runtime heap configuration

## 10. Limitations

1. **Small N.** 15 in-distribution and 15 OOD incidents per condition. One incident is worth 6.7 percentage points. All figures are indicative; no significance is claimed anywhere in this report.
2. **Synthetic incidents.** The dataset is generated, not harvested from a live cluster. Evidence shape matches what the watcher gathers, but real incidents are noisier and more ambiguous than these.
3. **Lexical overlap.** Kubernetes event strings such as `Back-off restarting failed container` appear verbatim in `crashloop-backoff.md`. They are the literal strings the kubelet emits, so removing them would make the dataset unrealistic - but they give crashloop retrieval a small boost over a purely semantic match.
4. **Relevance is not confidence.** Section 7 is an honest check on the escalation threshold, never a calibration claim.
5. **Single model family.** One embedding model, one LLM, greedy decoding - near-deterministic, not fully deterministic. Results are not portable to other model families.
6. **Rubric-bound grading.** Success is defined by the keyword rules in `validation/dataset/rubric.md`, frozen before the harness first ran. A correct diagnosis worded outside those lists is graded `NEEDS_HUMAN`, not wrong - but the rubric's coverage still bounds what the numbers can mean.

