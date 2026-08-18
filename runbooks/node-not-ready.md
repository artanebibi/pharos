# Node Not Ready

## Symptom
`kubectl get nodes` shows a node as `NotReady`. Pods on that node move to `Unknown` or `Terminating`, and after the default five-minute eviction toleration they are rescheduled elsewhere - or stay stuck if capacity is short. The defining characteristic is **blast radius**: many unrelated workloads degrade simultaneously, which separates this from any single-pod failure. `kubectl describe node` reports a stale `LastHeartbeatTime`, since the control plane is inferring the node's state from missing heartbeats rather than from a reported error.

## Root Causes
1. **kubelet stopped or cannot reach the API server** - the node may be perfectly healthy while its heartbeat is not arriving, which is indistinguishable from a dead node at the control plane.
2. **Disk pressure** - a full disk (usually image and log accumulation) causes the kubelet to set `DiskPressure`, stop accepting pods, and begin evicting; see `evicted-pods.md`.
3. **Memory pressure** - the node itself is exhausted, not just one container's cgroup.
4. **Network partition or CNI failure** - the node is running but isolated, so heartbeats and pod networking both fail.
5. **Container runtime down** - containerd or the equivalent has stopped, so the kubelet has nothing to report on.

## Diagnosis Steps
1. `kubectl get nodes` - establish how many nodes are affected. One node suggests a local fault; several at once suggests the control plane or the network.
2. `kubectl describe node <node>` - read the `Conditions` block: `Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`, and the heartbeat timestamps.
3. On the node, `systemctl status kubelet` and `journalctl -u kubelet -n 200` - the kubelet's own logs usually name the cause outright.
4. `df -h` on the node - check the filesystem backing images and logs, not just the root volume.
5. `crictl info` - confirm the container runtime is alive and responding.
6. On a local `kind` cluster the node is a container: `docker ps` and `docker logs <node>` are the equivalent of the two steps above.

## Remediation
1. **kubelet or runtime down** - restart the service and watch the node return to `Ready`; investigate the reason it stopped before considering it resolved.
2. **Disk pressure** - reclaim space by pruning unused images and rotating logs. Raising the eviction threshold buys time but is a stopgap, not a fix.
3. **Memory pressure** - reduce overcommit on the node, evict or reschedule the largest consumer, and set requests so the scheduler stops overfilling it.
4. **Network or CNI** - restart the CNI DaemonSet pod on the affected node and verify connectivity to the API server endpoint.
5. **Planned work** - `kubectl cordon` then `kubectl drain --ignore-daemonsets`, and `kubectl uncordon` afterwards, so eviction is orderly rather than abrupt.
6. Confirm the fix by watching the node report `Ready` and its pods return to `Running` on their own.
