#!/usr/bin/env bash
set -euo pipefail

FAILURE_TYPE="${1:-}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/workloads"

usage() {
  echo "Usage: $0 {crashloop|oom|cpu-throttle|clean}"
  exit 1
}

[[ -z "$FAILURE_TYPE" ]] && usage

case "$FAILURE_TYPE" in
  crashloop)     kubectl apply -f "$DIR/crashloop-demo.yaml" ;;
  oom)           kubectl apply -f "$DIR/oom-demo.yaml" ;;
  cpu-throttle)  kubectl apply -f "$DIR/cpu-throttle-demo.yaml" ;;
  clean)         kubectl delete -f "$DIR" --ignore-not-found ;;
  *)             usage ;;
esac
