# PVC Binding Failure

## Symptom
A pod stays in `Pending` and never reaches `Running`. `kubectl get pvc` shows the claim's `STATUS` as `Pending` rather than `Bound`. `kubectl describe pod` shows a `FailedScheduling` event reading `pod has unbound immediate PersistentVolumeClaims`. Unlike crashloop or OOM, **the container never starts at all** - there are no restarts and `kubectl logs` returns nothing, because there is no container to read logs from. The useful evidence is on the PVC and the scheduler, not in the application.

## Root Causes
1. **No matching StorageClass** - the claim names a `storageClassName` that doesn't exist, or it omits the field entirely on a cluster that has no default class, so nothing ever claims responsibility for provisioning it.
2. **Provisioner missing or unhealthy** - the CSI driver isn't installed, or its controller pod is crashlooping, so the claim is never acted on and accumulates no events at all.
3. **`WaitForFirstConsumer` deadlock** - the class binds late by design, but the pod can't be scheduled for an unrelated reason (taint, insufficient CPU/memory), so binding is never triggered. The volume waits for the pod and the pod waits for the volume.
4. **Topology or node-affinity mismatch** - a `local` or zone-bound PV exists only where the pod cannot be scheduled, so no valid node satisfies both constraints.
5. **Capacity or access-mode mismatch** - a statically provisioned PV smaller than the request, a `ReadWriteMany` claim against a class that only supports `ReadWriteOnce`, or a backing disk that is genuinely full.

## Diagnosis Steps
1. `kubectl get pvc -n <namespace>` - confirm `Pending` vs `Bound`, and note the requested size, access mode, and storage class.
2. `kubectl describe pvc <pvc>` - the `Events` section is the decisive evidence. Distinguish three cases:
   - `ProvisioningFailed` - a provisioner tried and failed; the message names the backend reason.
   - `WaitForFirstConsumer` - normal *until* a pod is scheduled; if it persists, the real problem is scheduling the pod.
   - no events at all - nothing is watching the claim; suspect a missing or dead provisioner.
3. `kubectl get storageclass` - does the named class exist, and is one marked default (`storageclass.kubernetes.io/is-default-class: "true"`)?
4. `kubectl describe pod <pod>` - read the full `FailedScheduling` message. If it names taints or insufficient resources rather than the volume, the volume is a *symptom* of an ordinary scheduling failure.
5. `kubectl get pv` - for statically provisioned volumes, compare `CAPACITY`, `ACCESS MODES`, and `nodeAffinity` against what the claim asks for and where the pod is allowed to run.
6. `kubectl get pods -n kube-system` - confirm the CSI controller/provisioner pods are `Running`. A crashlooping provisioner leaves *every* claim in the cluster `Pending`; diagnose it with the `crashloop-backoff.md` runbook.
7. `kubectl describe node` - check for a `DiskPressure` condition if provisioning fails at the backend rather than at the API level.

## Remediation
1. **Missing or wrong storage class** - correct `storageClassName`, or mark an existing class as default. Most of the PVC spec is immutable, so this usually means deleting and recreating the claim and its pod; **confirm there is no data to lose before deleting**.
2. **Provisioner down** - restore the CSI driver (`kubectl rollout restart deployment/<csi-controller> -n kube-system`). Pending claims bind on their own once it is healthy; they do not need to be recreated.
3. **`WaitForFirstConsumer` deadlock** - fix the pod's scheduling constraint (add the missing toleration, lower requests, free node capacity). Binding follows automatically the moment the pod schedules.
4. **Topology mismatch** - either constrain the pod to where the volume lives (`nodeSelector`/affinity matching the PV's `nodeAffinity`), or move to a class whose volumes are reachable from the pod's zone.
5. **Size or access mode** - request a size the backend supports, and for shared access use a class that genuinely offers `ReadWriteMany` (most block-storage classes do not). If the class sets `allowVolumeExpansion: true`, edit the claim's request instead of recreating it.
6. **Full disk** - reclaim space on the backing node or provision more capacity, then delete the pending pod so it reschedules.
7. Confirm the fix by watching the PVC move to `Bound` and the pod leave `Pending` for `Running`.
