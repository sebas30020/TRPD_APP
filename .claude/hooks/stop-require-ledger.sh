#!/usr/bin/env bash
# Stop hook: if the working tree changed but no ledger entry was recorded
# this session, block with exit 2 so the agent closes the loop (verify →
# avo-record) instead of walking away mid-attempt. Read-only sessions
# (clean working tree) pay no toll.
set -uo pipefail

INPUT="$(cat)"

json_field() {
  local field="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg f "$field" '.[$f] // empty' <<<"$INPUT" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys
try:
    d = json.loads(sys.argv[2])
    v = d.get(sys.argv[1])
    print(v if v is not None else "")
except Exception:
    print("")' "$field" "$INPUT" 2>/dev/null
  fi
}

# Recursion guard — confirmed pattern used elsewhere in this environment.
stop_hook_active="$(json_field stop_hook_active)"
if [[ "$stop_hook_active" == "true" ]]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(json_field cwd)"
  [[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="$(pwd)"
fi
cd "$PROJECT_DIR" 2>/dev/null || exit 0

AVO_DIR="$PROJECT_DIR/.avo"
[[ -d "$AVO_DIR" ]] || exit 0

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  exit 0
fi

session_id="$(json_field session_id)"
current_lines=0
[[ -f "$AVO_DIR/ledger.jsonl" ]] && current_lines="$(wc -l < "$AVO_DIR/ledger.jsonl" | tr -d ' ')"

if [[ -n "$session_id" ]]; then
  baseline_file="/tmp/avo-session-${session_id}.baseline"
  if [[ -f "$baseline_file" ]]; then
    baseline_lines="$(cat "$baseline_file" 2>/dev/null || echo 0)"
    if [[ "$current_lines" -gt "$baseline_lines" ]]; then
      exit 0
    fi
  else
    # No baseline recorded (e.g. SessionStart never ran for this session)
    # — don't block on a guess; a false block is worse than a rare miss.
    exit 0
  fi
else
  exit 0
fi

cat >&2 << 'MSGEOF'
[AVO HARNESS] Hay cambios en el árbol de trabajo sin registrar ningún
intento en .avo/ledger.jsonl durante esta sesión.

Antes de terminar:
  1. Ejecuta .avo/verify.sh (o .avo/bin/avo check) para obtener un veredicto.
  2. Usa la skill `avo-record` (o `.avo/bin/avo record <commit|reject|park> ...`)
     para registrar el intento y actualizar .avo/state.md.
MSGEOF
exit 2
