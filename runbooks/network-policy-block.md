# NetworkPolicy Block

## Symptom
Traffic between pods that should be able to communicate **times out** rather than being refused. Names resolve correctly, the Service has endpoints, both pods are `Running`, and Kubernetes reports no error anywhere - a denied packet is dropped silently, not rejected, so there is nothing to see in events or logs. The single most useful discriminator is the failure mode of the connection: `connection refused` means nothing is listening at the destination, while a **timeout** means the packet never arrived, which is what a policy denial looks like.

## Root Causes
1. **Default-deny with no matching allow rule** - any pod selected by a policy becomes deny-by-default for that direction, so adding a policy anywhere in the namespace can break traffic that was previously fine.
2. **Egress forgotten** - the server's namespace allows ingress but the client's namespace has an egress policy that does not allow the destination. Both directions must permit the flow independently.
3. **Selector semantics** - a bare `podSelector` matches only within the policy's own namespace; cross-namespace traffic requires `namespaceSelector`. An empty selector means "everything", not "nothing", which is an easy and dangerous misreading.
4. **DNS blocked as collateral** - a default-deny egress policy that omits port 53 breaks name resolution for the whole namespace, which usually surfaces first; see `dns-resolution-failure.md`.
5. **Port or protocol mismatch** - the rule allows the wrong port, or allows TCP where UDP is needed.
6. **The CNI does not enforce policy** - policies are accepted by the API server and quietly do nothing. This is the inverse failure and matters here: a local `kind` cluster's default CNI does not implement NetworkPolicy at all.

## Diagnosis Steps
1. From inside the client pod, establish timeout versus refusal - this one observation separates a policy problem from an application or Service problem before any YAML is read.
2. Confirm the Service layer is healthy first: `kubectl get endpoints <service>` must be populated, or you are chasing a policy for what is really a selector or readiness fault.
3. `kubectl get networkpolicy -A` - list every policy, not just the ones in the destination namespace, since the client's egress rules are equally capable of blocking the flow.
4. `kubectl describe networkpolicy <name>` - read `podSelector`, `policyTypes`, and the peer selectors literally, checking which namespace each selector is evaluated in.
5. Check both directions explicitly: egress from the client and ingress to the server. Fixing only one side is the most common incomplete fix.
6. Verify the CNI actually enforces policy before concluding a policy is at fault, and equally before trusting one to protect anything.

## Remediation
1. **Add the missing allow rule**, written as narrowly as still works - by pod label and port, not by opening the namespace.
2. **Always allow DNS egress** on **both UDP and TCP port 53** in any default-deny egress policy; a UDP-only rule fails intermittently when large responses fall back to TCP.
3. **Cross-namespace traffic** - use an explicit `namespaceSelector` with real labels rather than relying on a `podSelector` that silently scopes to the local namespace.
4. **Match port and protocol exactly** against what the application actually uses, including any sidecar or metrics port.
5. **Confirm causation before rewriting rules** - temporarily removing the suspected policy proves it is responsible, but restore a corrected policy immediately; leaving the namespace unprotected is not an acceptable resting state.
6. Confirm the fix by completing the connection that previously timed out, **and** by re-verifying that traffic the policy is meant to deny is still denied.
