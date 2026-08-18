# HPA Not Scaling

## Symptom
Load rises but the replica count does not follow. `kubectl get hpa` shows either `TARGETS` as `<unknown>/50%`, meaning no metric is arriving at all, or a real utilisation figure that never crosses the threshold. The workload sits at `minReplicas` while latency climbs and containers throttle. Nothing is in an error state - pods are `Running` and healthy - so this is a **silent failure to act** rather than a visible fault, which is why it is usually discovered during an incident rather than before one.

## Root Causes
1. **metrics-server missing or unhealthy** - the HPA has no metrics source, reports `<unknown>`, and makes no scaling decision at all rather than failing loudly.
2. **No resource requests on the container** - CPU utilisation is expressed as a percentage *of requests*. With no request there is no denominator, so no utilisation can be computed.
3. **Wrong target metric** - scaling on CPU for a workload bottlenecked on IO, queue depth, or downstream latency. CPU stays flat while the service degrades, and the HPA is behaving correctly on the wrong signal.
4. **Already at `maxReplicas`** - the HPA is scaling exactly as configured and has simply run out of room.
5. **New replicas cannot be scheduled** - the HPA does raise the desired count, but the new pods stay `Pending`; see `pod-pending.md`.

## Diagnosis Steps
1. `kubectl get hpa -n <namespace>` - read `TARGETS`, `MINPODS`, `MAXPODS`, and `REPLICAS` together; `<unknown>` versus a real number splits the causes immediately.
2. `kubectl describe hpa <name>` - the `Conditions` block is the most informative single output: `AbleToScale`, `ScalingActive`, and `ScalingLimited` each name a distinct blocker, and the events record recent decisions.
3. For `<unknown>`, run `kubectl top pods`. If that also fails, the fault is metrics-server, not the HPA.
4. Confirm the target container actually sets `resources.requests` - this is the most common cause of a permanently unknown CPU target.
5. `kubectl get deployment <name>` - if `DESIRED` rose but `READY` did not, the HPA worked and the problem moved to scheduling.
6. `ScalingLimited: True` means the HPA is capped, which is configuration rather than malfunction - check it before investigating anything else.

## Remediation
1. **Install or repair metrics-server**, and confirm with `kubectl top pods` before re-testing the HPA; nothing else can be assessed until metrics flow.
2. **Set CPU and memory requests** on the scaled container so utilisation has a denominator.
3. **Scale on a metric that tracks the real bottleneck** - queue depth or requests-per-second via custom or external metrics for IO-bound services, rather than forcing CPU to stand in for them.
4. **Raise `maxReplicas`** once you have confirmed the cluster can actually schedule the extra pods; raising it without capacity converts an HPA problem into a `Pending` pod problem.
5. **Account for stabilisation** - the default scale-down window is deliberately slow to prevent flapping. Tune the behaviour policies rather than concluding the HPA is broken because it reacted gradually.
6. Confirm the fix by generating representative load and watching replicas track it, then settle back down afterwards.
