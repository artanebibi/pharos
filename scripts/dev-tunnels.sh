set -uo pipefail
 
NS="monitoring"
PROM_SVC="svc/kube-prometheus-stack-prometheus"
AM_SVC="svc/kube-prometheus-stack-alertmanager"
 
PROM_LOG="/tmp/pharos-prom-pf.log"
AM_LOG="/tmp/pharos-am-pf.log"
 
cleanup() {
  echo
  echo "→ stopping port-forwards"
  [[ -n "${PROM_PID:-}" ]] && kill "$PROM_PID" 2>/dev/null || true
  [[ -n "${AM_PID:-}"   ]] && kill "$AM_PID"   2>/dev/null || true
  wait 2>/dev/null || true
  echo "  done."
}
trap cleanup EXIT INT TERM
 
echo "→ starting port-forward: Prometheus   (localhost:9090)"
kubectl port-forward -n "$NS" "$PROM_SVC" 9090:9090 > "$PROM_LOG" 2>&1 &
PROM_PID=$!
 
echo "→ starting port-forward: AlertManager (localhost:9093)"
kubectl port-forward -n "$NS" "$AM_SVC" 9093:9093 > "$AM_LOG" 2>&1 &
AM_PID=$!
 
# Give kubectl a moment to bind the ports before we probe.
sleep 2
 
check_forward() {
  local url="$1" name="$2" log="$3" pid="$4"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "✗ $name port-forward died. Last output:"
    cat "$log"
    exit 1
  fi
  if ! curl -sf -o /dev/null "$url"; then
    echo "✗ $name not responding at $url. Log:"
    cat "$log"
    exit 1
  fi
  echo "✓ $name responding at $url"
}
 
check_forward "http://localhost:9090/-/ready" "Prometheus"   "$PROM_LOG" "$PROM_PID"
check_forward "http://localhost:9093/-/ready" "AlertManager" "$AM_LOG"   "$AM_PID"
 
echo
echo "Both tunnels up. Press Ctrl+C to stop."
wait
