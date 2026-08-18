# Stuck Rollout

## Symptom
`kubectl rollout status deployment/<name>` hangs on `Waiting for deployment rollout to finish: N out of M new replicas have been updated`. The old pods keep serving, so there may be **no user-visible outage at all** - the deployment is simply frozen part-way. After `progressDeadlineSeconds` (600 by default) the deployment records `ProgressDeadlineExceeded`, but note that it **does not roll back on its own**: it stops and waits for a human. The new ReplicaSet exists with a non-zero desired count and never reaches it.

## Root Causes
1. **New pods never become Ready** - the rollout is blocked by an ordinary pod failure: an image that will not pull, a missing config key, or a failing probe. The rollout is the symptom, not the fault.
2. **`maxUnavailable: 0` with no spare capacity** - a new pod cannot be created until an old one is removed, and no old one may be removed. This is a genuine deadlock that will never resolve on its own.
3. **PodDisruptionBudget** - a budget that forbids dropping below the current replica count blocks the eviction of old pods.
4. **ResourceQuota exhausted** - the namespace quota rejects the new ReplicaSet's pods, so they are never created at all.
5. **No schedulable capacity** - the new pods are created but stay `Pending`; see `pod-pending.md`.

## Diagnosis Steps
1. `kubectl get rs -n <namespace>` - identify the new ReplicaSet and compare its `DESIRED`, `CURRENT`, and `READY` columns. The gap tells you which half of the problem you have.
2. Determine whether new pods **were never created** or **were created and are failing** - these lead to completely different investigations, and the ReplicaSet counts settle it in one command.
3. `kubectl get pods -l <selector>` - for pods belonging to the new ReplicaSet, their status *is* the root cause. Follow it into `image-pull-error.md`, `bad-configmap-rollout.md`, `liveness-probe-failure.md`, or `pod-pending.md`.
4. `kubectl describe deployment <name>` - read the `Conditions`: `Progressing`, `ProgressDeadlineExceeded`, and `ReplicaFailure`, which carries the API-level rejection reason when pods were never created.
5. Compare `maxUnavailable` and `maxSurge` against available headroom; `maxUnavailable: 0` on a full cluster is the classic deadlock.
6. `kubectl get resourcequota,pdb -n <namespace>` - check both, since each blocks a different half of the replace cycle.

## Remediation
1. **Fix what the new pods are failing on** - this is the real remediation, and the rollout resumes by itself with no further action once pods reach `Ready`.
2. **Restore service first if it is degraded** - `kubectl rollout undo deployment/<name>` returns to the last working revision; debug the failed revision afterwards rather than under pressure.
3. **Break the deadlock** - set `maxSurge` to at least 1 so a new pod can be created before an old one is removed.
4. **Quota or capacity** - raise the `ResourceQuota` or free cluster capacity, then let the existing ReplicaSet proceed; it does not need to be recreated.
5. **PodDisruptionBudget** - relax it temporarily for the rollout, and restore it immediately afterwards so the protection is not silently lost.
6. Confirm the fix by watching `kubectl rollout status` report completion and the old ReplicaSet scale to 0.
