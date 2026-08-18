# DNS Resolution Failure

## Symptom
Application logs show name-resolution errors for a service that exists - `no such host`, `Name or service not known`, `Temporary failure in name resolution`, or `getaddrinfo EAI_AGAIN`. Failures are frequently **intermittent and latency-shaped** rather than absolute: requests that eventually succeed but take ~5s, which is a resolver timeout followed by a retry. The pod itself stays `Running` with no restarts, unless the application exits on the error - in which case it presents as `CrashLoopBackOff` and the DNS cause is only visible in the previous container's logs. The clearest single signal is that **connecting by IP works while connecting by name fails**.

## Root Causes
1. **CoreDNS unavailable or degraded** - the CoreDNS pods are crashlooping, evicted, throttled, or scaled to zero. Every lookup in the cluster then fails or times out, so the blast radius is cluster-wide rather than one workload.
2. **`ndots` search-path amplification** - the default `ndots:5` means any hostname with fewer than five dots (in practice, nearly every external name) is first tried against each cluster search domain. Each attempt is a wasted query; under load this both adds latency and exhausts CoreDNS.
3. **Wrong name or wrong namespace** - a bare `<service>` only resolves within the same namespace. Cross-namespace calls need `<service>.<namespace>` or the fully qualified `<service>.<namespace>.svc.cluster.local`.
4. **Service exists but has no endpoints** - the name resolves while connections still fail, because the Service's selector matches no *ready* pod. This is a selector or readiness fault wearing a DNS costume.
5. **NetworkPolicy blocking egress to kube-dns** - a default-deny egress policy without an explicit rule for port 53 silently kills DNS for every pod in the namespace.
6. **Upstream resolver unreachable** - CoreDNS's `forward` target is down or filtered, so in-cluster names resolve normally while external names fail.

## Diagnosis Steps
1. Establish the name-vs-IP split from inside the failing pod, since that single fact separates DNS from general network failure. Many images have no `dig` or `nslookup`; `getent hosts <name>` uses the same resolver and is almost always present, or run a throwaway `kubectl run -it --rm dnsutils --image=<image with dig> --restart=Never`.
2. Narrow the scope before touching anything: in-cluster names only (suspect Service, selector, or namespace), external names only (suspect the CoreDNS `forward` upstream), or both (suspect CoreDNS itself or a NetworkPolicy).
3. `kubectl get pods -n kube-system -l k8s-app=kube-dns` - are the CoreDNS pods `Running` and `Ready`, and is the restart count climbing?
4. `kubectl logs -n kube-system -l k8s-app=kube-dns` - look for `plugin/errors`, `i/o timeout` against the upstream, or a flood of SERVFAILs.
5. `kubectl get endpoints <service> -n <namespace>` - an empty endpoint list means the Service has no ready backends, and DNS is not the fault at all.
6. `kubectl exec <pod> -- cat /etc/resolv.conf` - confirm `nameserver` is the kube-dns ClusterIP, and check the `search` list and the `ndots` option against what the application actually queries.
7. `kubectl get networkpolicy -n <namespace>` - a default-deny egress policy with no allowance for UDP and TCP 53 is a common cause; see `network-policy-block.md`.
8. Check CoreDNS's own CPU throttling and memory limits - a throttled resolver produces exactly the intermittent-timeout pattern above, and is diagnosed with `cpu-throttle.md`.

## Remediation
1. **CoreDNS unhealthy** - restore it first, because nothing else in the cluster is trustworthy while it is down: `kubectl rollout restart deployment/coredns -n kube-system`, and confirm at least two replicas spread across nodes.
2. **`ndots` latency** - set `dnsConfig.options` with `ndots: 2` on the workload, or use fully qualified names with a trailing dot for external hosts. Both remove the wasted search-domain lookups.
3. **Wrong name** - use `<service>.<namespace>` for cross-namespace calls, and keep the name in configuration rather than hardcoded, so a namespace move doesn't require a rebuild.
4. **No endpoints** - fix the Service selector or the readiness probe so pods actually become `Ready`; the endpoint list populates and the name starts working without any DNS change.
5. **NetworkPolicy** - add an explicit egress rule allowing **both UDP and TCP** port 53 to kube-system. TCP matters: large responses fall back to it, so a UDP-only rule fails intermittently and confusingly.
6. **Upstream unreachable** - correct the `forward` target in the CoreDNS ConfigMap, then `kubectl rollout restart deployment/coredns -n kube-system`, since the Corefile is not reliably hot-reloaded.
7. Confirm the fix by resolving the failing name from inside the affected pod, and by watching the application's resolution errors stop rather than merely slow down.
