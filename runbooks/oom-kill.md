# OOM-Kill

## Symptom
The container restarts repeatedly. `kubectl describe pod` shows
`Last State: Terminated`, `Reason: OOMKilled`, `Exit Code: 137`. `RESTARTS` count is climbing. The node may also show general memory
pressure if several pods are affected at once.

## Root Causes
1. **Memory limit set too low** for the container's working size.
2. **Memory leak or non-limit growth** - a heap that grows over the process's
   runtime, unclosed connection pool, or a non-limit in-memory growing cache.
3. **Traffic or batch-size spike** - a legitimate but unanticipated memory surge.
4. **Runtime not respecting the container's cgroup limit** -  a JVM
   without container-aware heap flags defaulting to a fraction of *host*
   memory rather than the container's actual limit.

## Diagnosis Steps
1. `kubectl describe pod` - confirm `Reason: OOMKilled` and confirm the actual memory limit.
2. Check the reason leading up to the kill: `kubectl top pod` (if `metrics-server` is installed) or the Grafana "Kubernetes / Compute Resources / Pod" dashboard.
3. Determine whether the growth was **gradual** or **sudden** / **immediate spike**.
4. Check the deployment history, analyze for configurations which might have affected the recent OOM.
5. For JVM or other managed-runtime workloads, check the heap flags against the container's memory limit.

## Remediation
1. **Short-term fix** - raise the memory limit to a value with margin above the observed working amount; optionally set a `VerticalPodAutoscaler` in recommendation-only mode to track the right size over time.
2. **Leak** - roll back the offending deploy; restart pods in the meantime to
   recover service while the underlying bug is fixed.
3. **Runtime flag issue** - set explicit heap flags (e.g. `-Xmx` comfortably below the container limit) or upgrade to a container-aware runtime version.
4. Confirm the fix by watching the memory-working-set-to-limit ratio stay stable (well under its alerting threshold) under representative load.