#!/usr/bin/env bash
set -euo pipefail

INCIDENT_ID="${1:-}"
RAG_ENGINE_URL="${RAG_ENGINE_URL:-http://localhost:8080}"

usage() {
  echo "Usage: $0 <incident_id>"
  exit 1
}

[[ -z "$INCIDENT_ID" ]] && usage

echo "→ approving incident $INCIDENT_ID"
curl -sf -X POST "$RAG_ENGINE_URL/incidents/$INCIDENT_ID/approve" > /dev/null

echo "→ memorizing incident $INCIDENT_ID"
RESPONSE=$(curl -sf -X POST "$RAG_ENGINE_URL/incidents/$INCIDENT_ID/memorize")

CORPUS_SIZE=$(echo "$RESPONSE" | grep -o '"corpus_size":[0-9]*' | grep -o '[0-9]*$')
echo "corpus_size: $CORPUS_SIZE"
