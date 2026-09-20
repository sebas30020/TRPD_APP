#!/usr/bin/env bash
# Feedback-anchored verification entrypoint — the one thing in this
# harness that is allowed to say no. Prints exactly one JSON object to
# stdout and exits 0 (pass) or 1 (fail). Diagnostic/build output goes to
# stderr, never stdout, so the JSON stays parseable.
#
# Contract: {"pass": bool, "metric_name": str|null, "metric_value": num|null,
#            "signals": [str, ...], "error_details": str|null}
#
# Non-negotiable: this script (and the profile it dispatches to) never
# asks the authoring agent whether the change is good. The signal must be
# producible without that opinion.
set -uo pipefail

AVO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="software"

if [[ -f "$AVO_DIR/config.json" ]]; then
  if command -v jq >/dev/null 2>&1; then
    detected="$(jq -r '.profile // "software"' "$AVO_DIR/config.json" 2>/dev/null)"
  elif command -v python3 >/dev/null 2>&1; then
    detected="$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("profile","software"))
except Exception:
    print("software")' "$AVO_DIR/config.json" 2>/dev/null)"
  elif command -v python >/dev/null 2>&1; then
    detected="$(python -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("profile","software"))
except Exception:
    print("software")' "$AVO_DIR/config.json" 2>/dev/null)"
  else
    detected="software"
  fi
  [[ -n "$detected" && "$detected" != "null" ]] && PROFILE="$detected"
fi

case "$PROFILE" in
  research) exec "$AVO_DIR/profiles/research.sh" ;;
  *)        exec "$AVO_DIR/profiles/software.sh" ;;
esac
