# Pod Pending

## Symptom
The pod stays `Pending` and is never assigned to a node - the `NODE` column in `kubectl get pods -o wide` is empty. `kubectl describe pod` shows a `FailedScheduling` event with a per-node tally such as `0/3 nodes are available: 1 node(s) had untolerated taint, 2 Insufficient cpu`. `RESTARTS` is 0 and there are no logs, because no container exists. The distinction that matters: **the scheduler could not place the pod at all**, which is a different failure from a pod that was placed and then could not start (see `image-pull-error.md` or `bad-configmap-rollout.md`).

## Root Causes
1. **Insufficient allocatable resources** - the sum of pod *requests* exceeds what is free. Scheduling is decided on requests, not usage, so a node that looks idle in `kubectl top` can still be completely full.
2. **Untolerated taint** - control-plane nodes carry a `NoSchedule` taint by default, and operators add their own; a pod without the matching toleration is rejected.
3. **Node selector or affinity too strict** - the required labels exist on no node, often because a label was renamed or never applied.
4. **Unbound PersistentVolumeClaim** - the pod cannot schedule until its volume binds; see `pvc-binding-failure.md`.
5. **Anti-affinity or topology spread constraints** - three replicas required on distinct nodes in a two-worker cluster can never all be placed.

## Diagnosis Steps
1. `kubectl get pod <pod> -o wide` - an empty `NODE` confirms this is a scheduling problem rather than a startup problem.
2. `kubectl describe pod <pod>` - read the **whole** `FailedScheduling` tally, not just its first clause. It reports every node and the reason each was rejected, and mixed reasons are common.
3. `kubectl describe node <node>` - compare `Allocatable` against `Allocated resources`; remember these are requests.
4. `kubectl describe node <node> | grep -i taint` - list taints, and check them against the pod's tolerations.
5. `kubectl get nodes --show-labels` - confirm the labels the pod's `nodeSelector` or affinity demands actually exist somewhere.
6. `kubectl get pvc -n <namespace>` - if the pod mounts a volume, an unbound claim is the likely cause and the scheduling message is only a symptom.

## Remediation
1. **Insufficient resources** - lower requests to values that reflect real usage, or add node capacity. Oversized requests are the most common cause and the cheapest to fix.
2. **Taints** - add the matching toleration to the pod, or remove the taint if it was applied unintentionally.
3. **Selector or affinity** - correct the selector, or label the node if the label was simply never applied.
4. **Unbound PVC** - resolve the claim first; scheduling then proceeds automatically with no change to the pod.
5. **Spread constraints** - relax `whenUnsatisfiable` to `ScheduleAnyway`, or reduce the replica count to what the cluster can actually host.
6. Confirm the fix by watching the pod acquire a `NODE` and move to `Running`.
