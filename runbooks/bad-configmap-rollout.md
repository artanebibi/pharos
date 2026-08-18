# Bad ConfigMap Rollout

## Symptom
A configuration change is followed by a failure, and it presents in one of two opposite ways. Either the pods refuse to start - `CreateContainerConfigError` when a referenced key is absent, or a pod wedged in `ContainerCreating` with `FailedMount` events when a referenced volume source is absent, both with `RESTARTS` at 0 and no logs. Or, more confusingly, **nothing happens at all**: the ConfigMap is updated, no error appears anywhere, and the pods keep serving the old values indefinitely. The tell in both cases is temporal rather than technical - the workload was healthy until a config change, and pods from the previous revision are still fine.

## Root Causes
1. **Missing key** - `env`/`envFrom` references a key that does not exist in the ConfigMap, or the ConfigMap does not exist in that namespace. The kubelet refuses to create the container and reports `CreateContainerConfigError`.
2. **Mount failure** - a volume references a ConfigMap or Secret that is absent, leaving the pod stuck in `ContainerCreating` rather than failing outright.
3. **Environment variables never update** - values from `env`/`envFrom` are injected once, at container start. Editing the ConfigMap cannot change the environment of a running container, so without a restart the change silently does not apply.
4. **Mounted files update lazily, and `subPath` never updates** - projected volumes refresh on the kubelet sync period plus cache TTL, so a change takes up to about a minute; a mount using `subPath` does not receive updates **at all**, for the lifetime of the pod.
5. **Content that is valid but wrong** - the config parses, the container starts, and the application then fails on a bad endpoint, credential, or limit. This presents as `CrashLoopBackOff` or as elevated errors, never as a config error.
6. **Immutable ConfigMap** - a ConfigMap created with `immutable: true` rejects updates outright, so the change appears to have been applied when it was refused.

## Diagnosis Steps
1. `kubectl get pods -n <namespace>` - note which of the four presentations you have: `CreateContainerConfigError`, stuck `ContainerCreating`, `CrashLoopBackOff`, or all-`Running`-but-behaving-wrong. Each points at a different root cause above.
2. `kubectl describe pod <pod>` - the events name the exact object and key, for example `couldn't find key <key> in ConfigMap <namespace>/<name>` or `MountVolume.SetUp failed ... not found`.
3. `kubectl get configmap <name> -n <namespace> -o yaml` - confirm it exists **in the pod's own namespace** (ConfigMaps are not visible across namespaces) and that key names match the manifest character for character, since they are case-sensitive.
4. `kubectl rollout history deployment/<name>` - establish whether a rollout actually occurred. Editing a ConfigMap does not trigger one, so the absence of a new revision is itself the finding in the "nothing happened" case.
5. Read the value from inside a running pod rather than from the ConfigMap: `kubectl exec <pod> -- env | grep <VAR>`, or `kubectl exec <pod> -- cat /etc/config/<file>`. What the container sees is the only evidence that settles a config-drift argument.
6. Check the pod spec for `subPath` on the mount - if it is there, the file will never change in place regardless of how long you wait.
7. If the container starts and then dies, the config was structurally accepted and the fault is in its content - continue with `crashloop-backoff.md` and `kubectl logs --previous`.

## Remediation
1. **Missing key or object** - create or correct it, then `kubectl rollout restart deployment/<name>`. Pods in `CreateContainerConfigError` do recover on their own once the key exists, but restarting makes the recovery immediate and observable rather than eventual.
2. **Mount failure** - same fix, after confirming the name and namespace; a ConfigMap in the wrong namespace is indistinguishable from a missing one from the pod's point of view.
3. **Stale environment variables** - roll the workload. A restart is the mechanism by which environment changes take effect, not a workaround for a bug.
4. **`subPath` mounts** - mount the whole volume at a directory instead, or accept that every change requires a rollout and make that explicit in the deployment process rather than leaving it as folklore.
5. **Make config changes trigger rollouts** - annotate the pod template with a hash of the ConfigMap contents, so any edit changes the template, produces a normal tracked revision, and becomes rollback-able. This converts invisible config drift into an auditable deploy and is the durable fix for this entire class of failure.
6. **Bad content** - `kubectl rollout undo deployment/<name>` to return to the last working revision first, then fix forward. Reverting the ConfigMap alone changes nothing until the pods restart.
7. Confirm the fix by reading the value from inside a **new** pod and watching `kubectl rollout status deployment/<name>` report all replicas updated and available.
