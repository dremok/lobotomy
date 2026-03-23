#!/usr/bin/env bash
# Pretty-print the latest cycle log. Usage:
#   ./tail.sh           — show latest cycle (human-readable)
#   ./tail.sh -f        — follow in real time
#   ./tail.sh -r        — show raw jsonl (no formatting)
#   ./tail.sh -f -r     — follow raw

set -euo pipefail
cd "$(dirname "$0")"

latest=$(find logs -name 'cycle_*.jsonl' -type f 2>/dev/null | sort | tail -1)

if [ -z "$latest" ]; then
    echo "No cycle logs found."
    exit 1
fi

follow=false
raw=false

for arg in "$@"; do
    case "$arg" in
        -f) follow=true ;;
        -r|--raw) raw=true ;;
    esac
done

echo "=== $latest ==="

# jq filter: extract readable events from stream-json
read -r -d '' JQ_FILTER << 'EOF' || true
if .type == "assistant" then
  (.message.content // [])[] |
    if .type == "text" then "💬 " + .text
    elif .type == "tool_use" then "🔧 " + .name + "(" + (.input | tostring | .[0:120]) + ")"
    else empty end
elif .type == "tool_result" then
  "   → " + ((.content // "done") | tostring | .[0:200])
elif .type == "result" then
  "\n=== RESULT (" + (.subtype // "unknown") + ", " + ((.duration_ms // 0) / 1000 | tostring | .[0:5]) + "s) ===\n" + (.result // "")
else empty end
EOF

if $raw; then
    if $follow; then
        tail -f "$latest"
    else
        cat "$latest"
    fi
elif $follow; then
    tail -f "$latest" | while IFS= read -r line; do
        echo "$line" | jq -r "$JQ_FILTER" 2>/dev/null
    done
else
    jq -r "$JQ_FILTER" "$latest" 2>/dev/null
fi
