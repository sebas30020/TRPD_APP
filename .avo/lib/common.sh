#!/usr/bin/env bash
# Shared utilities for the AVO harness: environment detection and a JSON
# helper layer with jq as the primary backend and a python3 fallback, so
# scripts don't hard-fail on minimal containers that lack jq.

avo_has() { command -v "$1" >/dev/null 2>&1; }

avo_json_tool() {
  if avo_has jq; then
    echo "jq"
  elif avo_has python3; then
    echo "python3"
  elif avo_has python; then
    echo "python"
  else
    echo "none"
  fi
}

# avo_json_valid <json-string>
avo_json_valid() {
  local json="$1"
  local tool
  tool="$(avo_json_tool)"
  case "$tool" in
    jq)
      jq -e . >/dev/null 2>&1 <<<"$json"
      ;;
    python3|python)
      "$tool" -c 'import json,sys; json.loads(sys.stdin.read())' <<<"$json" >/dev/null 2>&1
      ;;
    *)
      return 1
      ;;
  esac
}

# avo_json_get <json-string> <dotted.path> [default]
# Reads a scalar field. Missing path or missing tools both yield <default>.
avo_json_get() {
  local json="$1" path="$2" default="${3:-}"
  local tool
  tool="$(avo_json_tool)"
  case "$tool" in
    jq)
      # Deliberately NOT `.path // empty`: jq's `//` treats `false` (a
      # legitimate value, e.g. verify.pass=false) as falsy and would
      # silently fall through to <default>, same as a missing key.
      local out
      out="$(jq -r ".${path}" <<<"$json" 2>/dev/null)"
      if [[ -z "$out" || "$out" == "null" ]]; then
        out="$default"
      fi
      printf '%s' "$out"
      ;;
    python3|python)
      "$tool" -c '
import json, sys
path, default = sys.argv[1], sys.argv[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.stdout.write(default)
    sys.exit(0)
cur = data
for key in path.split("."):
    if isinstance(cur, dict) and key in cur:
        cur = cur[key]
    else:
        sys.stdout.write(default)
        sys.exit(0)
if cur is None:
    sys.stdout.write(default)
elif isinstance(cur, bool):
    sys.stdout.write("true" if cur else "false")
else:
    sys.stdout.write(str(cur))
' "$path" "$default" <<<"$json"
      ;;
    *)
      printf '%s' "$default"
      ;;
  esac
}

# avo_json_string <raw-text>
# Safely encodes arbitrary text as a JSON string literal (with quotes).
avo_json_string() {
  local text="$1"
  local tool
  tool="$(avo_json_tool)"
  case "$tool" in
    jq)
      # printf, not a here-string (<<<) — a here-string appends a newline
      # to stdin, which -Rs slurps in as a spurious trailing "\n".
      printf '%s' "$text" | jq -Rs .
      ;;
    python3|python)
      printf '%s' "$text" | "$tool" -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
      ;;
    *)
      # Minimal best-effort escaper: backslash, quote, and strip newlines.
      text="${text//\\/\\\\}"
      text="${text//\"/\\\"}"
      text="${text//$'\n'/ }"
      printf '"%s"' "$text"
      ;;
  esac
}

avo_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

avo_new_id() {
  if avo_has openssl; then
    openssl rand -hex 4
  elif [[ -r /proc/sys/kernel/random/uuid ]]; then
    tr -d '-' < /proc/sys/kernel/random/uuid | cut -c1-8
  else
    printf '%08x' "$((RANDOM * RANDOM))"
  fi
}
