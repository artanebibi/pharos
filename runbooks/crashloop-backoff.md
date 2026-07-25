# CrashLoopBackOff

## Symptom
Pod status shows `CrashLoopBackOff`. `kubectl get pods` shows a climbing `RESTARTS` count. `kubectl describe pod` shows a `Back-off restarting failed container` event with an increasing back-off delay (10s, 20s, 40s, ... capped around 5m). The container exits shortly after starting - within
seconds - **rather than running and then failing later**.

## Root Causes
1. **Application misconfiguration** - a missing required environment variable, config file, or secret causes the app to exit immediately on startup.
2. **Bad entrypoint/command** - wrong binary path, syntax error, or an unhandled exception during startup.
3. **Unavailable or misconfigured dependency at startup** - a database or service the app requires isnt reachable yet, and the app exits instead of retrying.

## Diagnosis Steps
1. `kubectl get pods -n <namespace>` - confirm status and restart count.
2. `kubectl logs <pod> --previous` - the *current* container has usually already restarted, so `--previous` is required to see the last crash reason of failure.
3. `kubectl describe pod <pod>` - check `Last State: Terminated`, the `Reason`, the `Exit Code`, and the `Events`.
4. Cross-reference the exit code:
   - `0` - clean exit (app logic finished and quit; not usually the intended
     behavior for a long-running service).
   - `1` - generic application error.
   - `137` - `SIGKILL`, often actually an OOM kill; check `Reason` for `OOMKilled` and use the `oom-kill.md` runbook instead if so.
   - `143` - `SIGTERM`, a graceful shutdown signal (probe failure, eviction, or rollout).
5. Check that the `ConfigMap`/`Secret` keys and environment variables the container references actually exist and match what's deployed.

## Remediation
1. **Missing config/secret** - create or correct the `ConfigMap`/`Secret`, then `kubectl rollout restart deployment/<name>`. If the reason is the secret itself, do more research to find the right data/key pairs rather than just creating it blindly
2. **Bad image or command** - fix the image tag or command, then `kubectl apply` the corrected manifest (or `kubectl rollout undo` if the previous revision was working).
3. **Probe misconfiguration** - adjust `initialDelaySeconds`,
   `failureThreshold`, or `periodSeconds` on the probe.
4. **Unavailable dependency** - verify the dependency's `Service`/`Endpoints` are correct; **consider an init container that waits for the dependency**, or retry logic in the app itself.
5. Confirm the fix with `kubectl rollout status deployment/<name>` and watch that the restart count stops climbing.