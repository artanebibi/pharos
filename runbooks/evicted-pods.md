# Evicted Pods

## Symptom
Multiple pods show status `Evicted`, often across several namespaces at once. `kubectl describe pod` gives a message such as `The node was low on resource: ephemeral-storage` or `memory`. Evicted pods are **not restarted in place** - they remain as dead objects and their replacement is scheduled elsewhere, so the list grows and never self-clears. The multi-workload blast radius distinguishes eviction from a per-container failure: this is the node protecting itself, not one application misbehaving.

## Root Causes
1. **Node memory pressure** - the kubelet evicts pods to keep the node itself alive, choosing victims by QoS class rather than by fault.
2. **Ephemeral storage pressure** - container logs, `emptyDir` volumes, or unpruned images fill the node's disk.
3. **QoS class** - `BestEffort` pods (no requests or limits at all) are evicted first, then `Burstable` pods exceeding their requests, and `Guaranteed` pods last. Omitting requests is what puts a workload at the front of the queue.
4. **Overcommit** - the sum of limits across scheduled pods far exceeds node capacity, so ordinary load is enough to trigger pressure.
5. **One noisy neighbour** - a single pod consuming disk or memory gets *other* pods evicted, so the victims are not the cause.

## Diagnosis Steps
1. `kubectl get pods -A --field-selector status.phase=Failed` - list every evicted pod at once; the spread across namespaces is itself diagnostic.
2. `kubectl describe pod <pod>` - the eviction message names the exhausted resource, which decides everything that follows.
3. `kubectl describe node <node>` - check the `MemoryPressure` and `DiskPressure` conditions and the `Allocated resources` summary.
4. `kubectl get pod <pod> -o jsonpath='{.status.qosClass}'` - a `BestEffort` result explains why *this* pod was chosen over its neighbours.
5. Identify the actual consumer with `kubectl top pods --all-namespaces --sort-by=memory`, or by inspecting disk usage on the node. The evicted pod is rarely the culprit.
6. Distinguish this from an OOM kill: eviction is a node-level, comparatively graceful decision recorded on the pod, whereas `OOMKilled` with exit code 137 is a cgroup-level kill of one container - use `oom-kill.md` for that.

## Remediation
1. **Set requests and limits** on anything that matters, so it is `Burstable` or `Guaranteed` rather than first in line for eviction. This is the single highest-value change.
2. **Reclaim disk** - prune images, rotate and cap container logs, and move large writes off `emptyDir` onto a PersistentVolume.
3. **Reduce overcommit** - bring scheduled requests in line with real capacity, or add nodes; see `node-not-ready.md` if the node has already gone unhealthy.
4. **Protect critical workloads** with a `PriorityClass`, so eviction chooses lower-priority pods first.
5. **Delete the accumulated `Evicted` objects** once the cause is fixed - they consume no resources but obscure the state of the cluster.
6. Confirm the fix by watching the node's pressure conditions clear and no new evictions appear under representative load.
