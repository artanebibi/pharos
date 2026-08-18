# Image Pull Error

## Symptom
The pod never starts. `kubectl get pods` shows `ErrImagePull`, then `ImagePullBackOff` once the kubelet begins backing off between attempts. The two statuses alternate, which can look like flapping but is one single unresolved failure. `RESTARTS` stays at **0** and `kubectl logs` returns nothing, because no container was ever created - this is the clearest separation from `CrashLoopBackOff`, where the container does start and then dies. The decisive evidence is the registry's own error string, carried verbatim in the pod's events.

## Root Causes
1. **Wrong image name or tag** - a typo, a tag that was never pushed, or a tag that has since been deleted. The registry answers `manifest unknown` or `not found`.
2. **Private registry with missing or expired credentials** - no `imagePullSecrets` on the pod or its ServiceAccount, a secret of the wrong type, or an expired token. Note that many registries deliberately answer `not found` rather than `unauthorized` for private repositories, so a "not found" does **not** rule out an authentication problem.
3. **Registry rate limit** - anonymous pulls are capped per source IP, and every node behind one NAT address shares that budget, so a cluster exhausts it far faster than a laptop does. The registry answers `toomanyrequests`.
4. **Registry unreachable** - blocked egress, a proxy, or a failure resolving the registry hostname (see `dns-resolution-failure.md`). The message is `dial tcp: i/o timeout` or `no such host`.
5. **Platform mismatch** - an image built only for `arm64` scheduled onto `amd64` nodes, reported as `no match for platform in manifest`.
6. **Image exists only on the build host** - on a local `kind` cluster an image built on the host is invisible to the nodes until it is explicitly loaded, and `imagePullPolicy: Always` forces a remote pull even after it has been.

## Diagnosis Steps
1. `kubectl get pods -n <namespace>` - confirm `ErrImagePull`/`ImagePullBackOff` and that `RESTARTS` is 0.
2. `kubectl describe pod <pod>` - the `Events` section carries the registry's response word for word. Read it literally; almost every cause below is distinguishable from that one string.
3. Map the message to the cause:
   - `manifest unknown` / `not found` - the repository or tag does not exist as spelled, **or** it is private and the pull was anonymous.
   - `unauthorized` / `pull access denied` - credentials are missing, wrong, or expired.
   - `toomanyrequests` - registry rate limit, not a configuration fault.
   - `i/o timeout` / `no such host` - network egress or DNS, not the image.
   - `no match for platform in manifest` - architecture mismatch.
4. Try the same reference by hand from a machine with the same credentials (`docker pull <image>`). This separates "the cluster cannot pull it" from "nobody can pull it", which are very different investigations.
5. `kubectl get serviceaccount <sa> -o yaml` and the pod spec - check where `imagePullSecrets` is expected to come from, and that the referenced secret is type `kubernetes.io/dockerconfigjson`.
6. For a mutable tag such as `latest`, confirm what it currently resolves to - a tag that moved or was overwritten produces a failure with no manifest change on your side.
7. On `kind`, check whether the node has the image at all: `docker exec <node> crictl images`.

## Remediation
1. **Wrong reference** - correct the image or tag and re-apply, or `kubectl rollout undo deployment/<name>` if the previous revision pulled cleanly.
2. **Missing credentials** - create a `dockerconfigjson` secret and attach it to the pod spec or the ServiceAccount, then `kubectl rollout restart deployment/<name>` so the kubelet retries immediately rather than waiting out a back-off that can already be minutes long.
3. **Rate limit** - authenticate even for public images, since an authenticated account has a higher cap, or mirror the image into a registry you control. Simply waiting restores service but fixes nothing.
4. **Unreachable registry** - repair egress, proxy configuration, or DNS, and verify from a debug pod on the same node rather than from your workstation.
5. **Platform mismatch** - use a multi-architecture tag, or build for the architecture the nodes actually run.
6. **Local `kind` image** - `kind load docker-image <image> --name <cluster>`, and set `imagePullPolicy: IfNotPresent`; with `Always` the kubelet ignores the loaded copy and goes to the registry regardless.
7. Confirm the fix by watching the pod leave `ImagePullBackOff` for `Running`, with a `Pulled` event in `kubectl describe pod`.
