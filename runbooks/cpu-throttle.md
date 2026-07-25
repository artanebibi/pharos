# CPU Throttle

## Symptom
The application is slow or high-latency despite *reported CPU usage* looking low relative to node capacity. `kubectl top pod` shows usage near or at the CPU limit. In Prometheus, the ratio `container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total` is elevated (above ~0.25–0.5). Unlike crashloop or OOM, **there are no restarts** - this is a silent performance degradation, not a
crash, which is exactly why relying on restart-count alone as a health signal completely misses it.

## Root Causes
1. **CPU limit set far below actual need under load**.
2. **Requests set too low**, causing poor scheduling placement.
3. **Bursty workloads** - batch or cron-like spikes hitting a limit sized for steady-state traffic.
4. **Inefficient code path** consuming more CPU than expected for specific inputs, independent of any misconfiguration.

## Diagnosis Steps
1. Confirm via the CFS throttle ratio in Prometheus (this is exactly the signal the `PodCPUThrottlingHigh` alert watches).
2. `kubectl describe pod` - check the configured `requests`/`limits`.
3. Compare the usage pattern over time (steady vs. bursty) via Grafana.
4. Check whether colocated pods on the same node are also under CPU pressure - that points to node-level contention rather than a pure per-pod limit problem.
5. If the limit already looks reasonable and throttling still occurs, troubleshoot the application - it may be a genuine inefficiency, not a misconfiguration.

## Remediation
1. **Raise the CPU limit** (or remove it and rely on requests plus node-level capacity - discuss the trade-off: no limit risks noisy-neighbor effects).
2. **Right-size requests** to reduce scheduling/bin-packing contention.
3. For bursty workloads, consider a `HorizontalPodAutoscaler` on CPU, or move
   batch work off the latency-sensitive hot path.
4. Re-check the throttle ratio after the change and confirm it drops back
   below the alert threshold.