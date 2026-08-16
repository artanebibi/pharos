# Pharos Validation Rubric - Phase 1f

**Frozen at first execution of `run_harness.py`** (commit timestamp is the
evidence). Written before any result is seen, so the criteria can't be bent to
fit what the model happened to produce. If a diagnosis looks right to you but
this rubric grades it wrong, the rubric wins - record the disagreement in
`report.md` as a limitation of the rubric, don't edit the rubric.

The same rubric, unmodified, grades both conditions. That is what makes the
RAG-vs-no-RAG delta meaningful: retrieval is the only variable that changes.

---

## 1. What is graded

| Input | Used for |
|---|---|
| `root_cause` | root-cause match |
| `remediation_steps` + `kubectl_commands`, concatenated | remediation match |
| HTTP status | `ERROR` grade |

**Not graded:** `reasoning` (long, enumerates every failure mode, would match
everything), `severity` (no ground truth in the dataset), `sources_used`, `retrieval_relevance_score` (grading on it
would manufacture the correlation  is meant to test).

## 2. Normalization

Case-insensitive substring match. Both response text and keywords normalized:
lowercase -> replace `-` `_` `/` and backticks with a space -> strip `*` `#` ->
collapse whitespace.

So `OOMKilled`->`oomkilled`, `out-of-memory`->`out of memory`, `-Xmx`->`xmx`.
**All keywords below are already normalized.** Substrings match inside words on
purpose: `throttl` catches throttled/throttling/throttle; `autoscal` catches
autoscaler/autoscaling.

## 3. Labels (closed set - `generate_dataset.py` may emit nothing else)

| `failure_type` | `expected_root_cause_category` | `expected_runbook` |
|---|---|---|
| `crashloop` | `missing_config`, `bad_command`, `dependency_unavailable` | `crashloop-backoff.md` |
| `oom` | `memory_limit_too_low`, `memory_leak`, `runtime_heap_misconfig` | `oom-kill.md` |
| `cpu_throttle` | `cpu_limit_too_low`, `bursty_workload` | `cpu-throttle.md` |

Each category is taken from the **Root Causes** section of the matching
runbook, so every in-distribution incident has a grounded answer available.

**OOD** (`is_ood: true`, `expected_runbook: null`) - no runbook exists:
`dns_resolution_failure`, `image_pull_error`, `network_policy_block`,
`pvc_binding_failure`, `hpa_not_scaling`. If any of these runbooks is written
later, the OOD half is invalidated and must be re-labelled.

## 4. Root-cause markers

**Category-specific** (any-of):

| Category | Markers |
|---|---|
| `missing_config` | `missing config`, `missing configuration`, `configmap`, `config map`, `environment variable`, `env var`, `secret`, `missing required`, `not set`, `unset`, `missing env`, `misconfiguration` |
| `bad_command` | `entrypoint`, `entry point`, `exec format`, `no such file`, `command not found`, `bad command`, `wrong command`, `invalid command`, `binary`, `image tag`, `wrong image`, `startup exception`, `unhandled exception`, `syntax error` |
| `dependency_unavailable` | `dependency`, `dependencies`, `upstream`, `connection refused`, `cannot connect`, `unable to connect`, `unreachable`, `not reachable`, `service unavailable` |
| `memory_limit_too_low` | `memory limit`, `limit too low`, `limit is too low`, `insufficient memory`, `undersized`, `exceeds its memory`, `exceeded its memory`, `limit lower than` |
| `memory_leak` | `memory leak`, `leak`, `unbounded growth`, `unbounded cache`, `grows over time`, `growing heap`, `connection pool`, `retained` |
| `runtime_heap_misconfig` | `heap space`, `heap size`, `max heap`, `heap flag`, `xmx`, `jvm`, `container aware`, `not container aware`, `runtime flag`, `garbage collect`, `gc setting` |
| `cpu_limit_too_low` | `cpu limit`, `limit too low`, `limit is too low`, `cfs quota`, `quota`, `insufficient cpu`, `limit below` |
| `bursty_workload` | `burst`, `bursty`, `spike`, `spiky`, `batch job`, `batch work`, `periodic`, `cron`, `traffic surge` |

Markers naming a *component* rather than a *failure condition* are deliberately
excluded, because they collide with a sibling category and send correct
diagnoses to manual grading via R2. Two were removed after testing the rules
against worked examples (before the freeze): bare `database` from
`dependency_unavailable`, which matched every `DATABASE_URL`-not-set diagnosis -
a missing-config case; and bare `heap` from `runtime_heap_misconfig`, which
matched `growing heap` and so caught every memory-leak diagnosis. The remaining
markers in both sets all name failure conditions, not components.

**Failure-type generic** - identifies the failure mode but not the cause:

| Type | Markers |
|---|---|
| `crashloop` | `crashloopbackoff`, `crash loop`, `crashloop`, `back off restarting`, `backoff restarting`, `container exit`, `container exited`, `exit code`, `exits immediately`, `fails to start`, `failing to start`, `restarting repeatedly`, `keeps restarting`, `startup failure` |
| `oom` | `oomkilled`, `oom kill`, `oom`, `out of memory`, `exit code 137`, `code 137`, `memory pressure`, `memory exhaust`, `killed by the kernel` |
| `cpu_throttle` | `throttl`, `cfs`, `cpu limit`, `cpu saturation`, `cpu pressure`, `cpu contention` |

**Failure-type exclusive** - diagnostic of one type and no other; used only to
detect a confident diagnosis of the *wrong* failure mode. Deliberately narrower
than the generic sets: "restarts climbing" is true of both crashloop and OOM, so
it appears in neither.

| Type | Markers |
|---|---|
| `crashloop` | `crashloopbackoff`, `crash loop`, `back off restarting`, `backoff restarting` |
| `oom` | `oomkilled`, `oom kill`, `out of memory`, `exit code 137`, `code 137` |
| `cpu_throttle` | `throttl`, `cfs` |

**OOD categories:**

| Category | Markers |
|---|---|
| `dns_resolution_failure` | `dns`, `coredns`, `resolv`, `ndots`, `name resolution`, `nxdomain`, `no such host`, `service discovery`, `lookup failed` |
| `image_pull_error` | `image pull`, `imagepull`, `errimagepull`, `imagepullbackoff`, `registry`, `pull access denied`, `manifest unknown`, `image not found`, `pull secret` |
| `network_policy_block` | `network policy`, `networkpolicy`, `traffic denied`, `traffic blocked`, `blocked by`, `egress`, `ingress rule`, `firewall`, `namespace selector` |
| `pvc_binding_failure` | `pvc`, `persistentvolumeclaim`, `persistent volume`, `storage class`, `storageclass`, `volume binding`, `unbound`, `provisioner` |
| `hpa_not_scaling` | `hpa`, `horizontalpodautoscaler`, `autoscal`, `metrics server`, `target metric`, `not scaling`, `unable to fetch metrics` |

## 5. Remediation markers

Matched over `remediation_steps` + `kubectl_commands` joined. A remediation
matches iff **(any ACTION) AND (that category's ARTIFACT)** are both present -
requiring both stops a generic "restart the deployment" from satisfying every
category.

**ACTION (shared):** `create`, `add`, `set`, `fix`, `correct`, `update`,
`raise`, `increase`, `adjust`, `patch`, `restart`, `rollout`, `undo`,
`roll back`, `rollback`, `revert`, `scale`, `apply`, `configure`, `redeploy`,
`remove`, `delete`, `bump`, `right size`, `resize`

| Category | ARTIFACT |
|---|---|
| `missing_config` | `configmap`, `config map`, `secret`, `environment variable`, `env var`, `configuration`, `missing variable` |
| `bad_command` | `image`, `tag`, `command`, `entrypoint`, `args`, `manifest`, `revision` |
| `dependency_unavailable` | `init container`, `initcontainer`, `service`, `endpoint`, `dependency`, `retry`, `readiness` |
| `memory_limit_too_low` | `memory limit`, `limits memory`, `memory`, `vpa`, `verticalpodautoscaler` |
| `memory_leak` | `deploy`, `deployment`, `revision`, `previous`, `leak`, `pod` |
| `runtime_heap_misconfig` | `heap`, `xmx`, `jvm`, `runtime`, `flag` |
| `cpu_limit_too_low` | `cpu limit`, `limits cpu`, `cpu`, `request`, `requests` |
| `bursty_workload` | `hpa`, `horizontalpodautoscaler`, `autoscal`, `cpu`, `batch`, `schedule` |

`memory_leak` and `bursty_workload` have loose artifact sets because their
runbook remedies are themselves loose ("roll back the offending deploy",
"consider an HPA"). Disclosed here; don't read those two rates strictly.

## 6. Grading - in-distribution (`is_ood: false`)

First rule that fires wins.

| # | Condition | Grade |
|---|---|---|
| R0 | non-2xx HTTP response | `ERROR` |
| R1 | `root_cause` == `unknown_failure_mode` | `ESCALATED` |
| R2 | matches >=2 category-specific sets **of the expected type** | `NEEDS_HUMAN` |
| R3 | matches the **expected category's** specific set | `CORRECT` if remediation matches, else `PARTIALLY_CORRECT` |
| R4 | matches a **different category of the same type** (right mode, wrong cause) | `PARTIALLY_CORRECT` |
| R5 | matches the expected type's **generic** set | `NEEDS_HUMAN` if it also matches another type's exclusive set, else `PARTIALLY_CORRECT` |
| R6 | matches exactly one **other** type's exclusive set | `INCORRECT` |
| R7 | nothing matched | `NEEDS_HUMAN` |

Two orderings are load-bearing:

- **R3 before R6** - "OOMKilled, causing the container to enter CrashLoopBackOff"
  on an OOM incident is correct *and* mentions another type's exclusive marker.
  The expected-category match wins; only responses matching nothing of the
  expected type reach R6.
- **R7 is `NEEDS_HUMAN`, not `INCORRECT`** - unmatched text may be a correct
  diagnosis worded in a way these lists don't anticipate. Scoring it wrong would
  let gaps in my keyword lists show up as system failures.

### OOD (`is_ood: true`)

| # | Condition | Grade |
|---|---|---|
| O0 | non-2xx | `ERROR` |
| O1 | `root_cause` == `unknown_failure_mode` | `ESCALATED` - **the desired outcome** |
| O2 | matches >=2 OOD category sets | `NEEDS_HUMAN` |
| O3 | matches this incident's own OOD category | `OOD_ANSWERED_PLAUSIBLE` |
| O4 | otherwise | `OOD_ANSWERED_WRONG` |

`OOD_ANSWERED_PLAUSIBLE` is **not** a success - the system was asked to escalate
what it can't ground and didn't. It's reported separately from
`OOD_ANSWERED_WRONG` because "confidently wrong on an unknown failure" and
"unguardedly right" are different behaviours and collapsing them hides that.

## 7. Grades -> metrics

*N* = 15 in-distribution incidents per condition.

- **Primary success rate** = (`CORRECT` + `PARTIALLY_CORRECT`) / *N*. Escalations,
  errors and unresolved `NEEDS_HUMAN` sit in the denominator. **Headline number.**
- **Strict success rate** = `CORRECT` / *N*.
- **Conditional accuracy** = (`CORRECT` + `PARTIALLY_CORRECT`) / (*N* - `ESCALATED`
  - `ERROR`), always printed with its own n, never as the headline.
- **False-escalation rate** = `ESCALATED` / *N* (in-distribution) - cost of the floor.
- **OOD escalation rate** = `ESCALATED` / 15 (OOD) - benefit of the floor.
- **Error rate** = `ERROR` / 30.

Escalations stay in the primary denominator deliberately. On the flattering
convention a system that escalated 14 of 15 and got the last one right would
report 100%.

## 8. Measured, not graded

- **Citation validity** - a `sources_used` entry is valid iff it exactly equals a
  chunk id the retriever actually returned. Valid shapes: `<file>.md::<Section>`
  (`Symptom` | `Root Causes` | `Diagnosis Steps` | `Remediation`) and
  `incident::<namespace>/<pod_name>`. Rate = valid/total per response; `null` for
  escalations and for `rag_off` (no chunks existed, so scoring it 0% would measure
  the setup, not the model - count any `rag_off` citation as a **fabricated
  citation** instead).
- **Precision@5 / MRR** - computed from the retriever's returned chunk ids, not
  from `sources_used`. **Precision@5 is capped at 0.8**: each runbook contributes
  exactly 4 chunks, so a perfect retriever scores 0.8, not 1.0. Print the cap next
  to the number or it reads as a failure. `n/a` for `rag_off` and OOD.

## 9. NEEDS_HUMAN

`grade.py` prints the count per condition. The human resolves each by applying
- as written - deciding which rule *should* have fired given wording the
lists missed, not judging freely whether the answer was good.

- Grade **blind to condition**: sort `grades.csv` so the two conditions for one
  incident aren't adjacent, and ignore the condition column while grading.
- One-line reason per manual grade in `human_note`.
- If >=20% land in `NEEDS_HUMAN`, say so in `report.md` - the headline numbers are
  then partly human judgement and that must be visible.
- `grades.csv` is committed (contains human judgement, not regenerable).

## 10. Constraints on `generate_dataset.py`

1. `expected_root_cause_category` in  only; anything else -> `grade.py` aborts.
2. **No exit-code-137 crashloops.** `crashloop-backoff.md` itself redirects 137 to
   `oom-kill.md`, so such an instance has two defensible answers and R6 would grade
   a right answer wrong. Use exit 1, 0, or another non-137 code.
3. **Pod names must not encode the failure type** - `checkout-api-7f9d`, not
   `crashloop-demo-...`. The pod name reaches the LLM in the prompt; a name like
   `oom-demo` hands over the answer.
4. Metric keys must match what the watcher emits: `restart_count`,
   `memory_working_set_ratio`, `cpu_throttle_ratio`. Absent metrics are **omitted,
   not zero-filled** - the watcher omits a key when Prometheus returns no data.
5. CPU-throttle instances carry no restarts (`cpu-throttle.md`: degradation
   without crashes).
6. Log wording varies across the 5 instances of a type and is never copied from a
   runbook - verbatim overlap makes retrieval match on strings, not semantics, and
   Precision@5 would measure nothing.
7. OOD instances must not use crashloop/OOM/CPU-throttle vocabulary. An OOD
   incident whose logs say `OOMKilled` will legitimately retrieve `oom-kill.md`
   above the floor and would measure the dataset's sloppiness, not the OOD floor.

## 11. Amendments

Frozen at first harness run. Amend only if genuinely defective, and then: log it
below with date and reason, **re-grade both conditions from scratch** (grading one
condition under v1 and the other under v2 destroys the comparison), and state the
effect on the headline numbers in `report.md`.

| Date | Change | Reason | Re-graded |
|---|---|---|---|
| - | none | frozen at initial commit | - |
