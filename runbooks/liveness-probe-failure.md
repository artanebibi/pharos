# Liveness Probe Failure

## Symptom
The container restarts repeatedly and `kubectl describe pod` shows `Killing container with id ...: Liveness probe failed`, along with the probe's own reason - a timeout, `connection refused`, or an unexpected HTTP status. `Last State: Terminated` reports `Exit Code: 143` (`SIGTERM`), not `1` and not `137`. This looks like `CrashLoopBackOff` and is frequently misdiagnosed as one, but **the application did not crash - Kubernetes killed it**. The strongest tell is that the application answers correctly when queried by hand while the probe continues to fail.

## Root Causes
1. **`initialDelaySeconds` shorter than real startup time** - the probe begins before the application is listening, kills it mid-boot, and it never once reaches a healthy state. This produces a permanent restart loop from a completely healthy application.
2. **`timeoutSeconds` too aggressive** - a probe budget below the endpoint's real latency under load, so restarts cluster precisely when the service is busiest.
3. **The probe endpoint does too much** - a liveness handler that checks the database or a downstream API converts *their* slowness into restarts of a healthy pod, turning a dependency blip into a self-inflicted outage.
4. **Wrong port or path** - the probe gets `connection refused` or a 404 from the first attempt onward.
5. **CPU starvation** - a throttled container cannot answer within the timeout even though nothing is wrong with it; see `cpu-throttle.md`.

## Diagnosis Steps
1. `kubectl describe pod <pod>` - confirm the `Liveness probe failed` event and note its specific reason; timeout, refusal, and bad status point at different causes.
2. Check the exit code: `143` means the container was signalled, which is this runbook. `137` means it was killed hard and is usually memory - use `oom-kill.md`.
3. `kubectl exec <pod> -- curl -sv localhost:<port><path>` - query the probe endpoint from inside the container. A fast, correct answer proves the probe configuration is wrong rather than the application.
4. Compare `initialDelaySeconds` against the startup time visible in the container's own logs, measuring from process start to "listening".
5. Check whether restarts correlate with traffic peaks, which points at timeout or saturation rather than misconfiguration.
6. Read what the probe handler actually does; a handler that touches dependencies is a design fault regardless of the current failure.

## Remediation
1. **Slow startup** - add a `startupProbe`. This is the correct fix rather than inflating `initialDelaySeconds`, because it permits a long boot window while keeping liveness tight once the container is up.
2. **Aggressive timeout** - raise `timeoutSeconds` and `failureThreshold` to reflect observed p99 latency, not the average.
3. **Overreaching handler** - make liveness shallow, answering only "is this process alive". Dependency checks belong in the readiness probe, where failure removes the pod from the Service instead of killing it.
4. **Wrong port or path** - correct them and re-apply; this failure appears immediately and consistently, never intermittently.
5. **CPU starvation** - raise the limit or reduce load, then re-check the throttle ratio.
6. Confirm the fix by watching the restart count stop climbing and the `Liveness probe failed` events stop appearing.
