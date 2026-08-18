# High Error Rate

## Symptom
The service returns errors - a rising 5xx ratio, failed requests, or client-visible timeouts - while **every Kubernetes-level signal looks healthy**. Pods are `Running`, `RESTARTS` is 0, probes pass, and the Service has endpoints. There is no failing object to inspect, which is precisely what makes this class hard: the evidence lives in metrics and application logs rather than in `kubectl describe`. Latency usually rises alongside the error ratio, and the two together are more informative than either alone.

## Root Causes
1. **A failing or slow upstream dependency** - a database, cache, or downstream API degrades and the failure cascades outward, so the service reporting errors is rarely the service at fault.
2. **A recent deploy** - a regression shipped in the current revision. Correlation with rollout time is the fastest discriminator available and should be checked before anything else.
3. **Saturation** - CPU throttling, exhausted connection pools, or thread starvation. The application is not broken, it is simply out of capacity; see `cpu-throttle.md`.
4. **A single bad replica** - one pod serving errors while the others are fine, producing a fractional error rate that matches its share of traffic almost exactly.
5. **Missing timeouts or circuit breaking** - one slow dependency consumes every worker, converting a partial degradation into a total outage of an otherwise healthy service.

## Diagnosis Steps
1. Correlate the error rate against deploy time first. If it starts at a rollout, the investigation is essentially over and the remediation is a rollback.
2. Break the error rate down **per pod**. A rate that concentrates in one replica means a bad instance; one spread evenly across all replicas means a shared cause - dependency, config, or load.
3. Check the dependency's own error rate and latency before investigating your own service, since a cascading failure is diagnosed from the wrong end otherwise.
4. `kubectl logs <pod>` - classify what the errors actually are. `connection refused`, a resolver timeout, a 500 from your own code, and an upstream 503 point in four different directions.
5. `kubectl get endpoints <service>` - confirm every endpoint should be receiving traffic. A pod that is unhealthy but still `Ready` indicates the readiness probe is not testing anything meaningful.
6. Check the CPU throttle ratio and memory-to-limit ratio over the same window, to rule saturation in or out rather than assuming a logic fault.

## Remediation
1. **Roll back** if the errors correlate with a deploy - `kubectl rollout undo deployment/<name>`. Restore service first and diagnose the bad revision afterwards.
2. **Remove the bad replica** - deleting the pod is sufficient when the failure is isolated to one instance, and the ReplicaSet replaces it automatically.
3. **Fix the dependency**, and add the timeout and circuit-breaker behaviour whose absence let a partial failure become a complete one.
4. **Relieve saturation** - scale out, raise limits, or enlarge the connection pool, guided by which resource the metrics show as exhausted.
5. **Tighten the readiness probe** so that a replica which cannot serve is removed from the endpoint list automatically instead of continuing to receive traffic.
6. Confirm the fix by watching the error ratio return to its baseline and stay there under representative load, not merely during a quiet period.
