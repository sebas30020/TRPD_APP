#!/usr/bin/env bash
# SessionStart hook (Gemini CLI): injects .avo memory (current state,
# recent ledger entries, recent dead ends) as context so the agent
# resumes from where the project actually is. Gemini's SessionStart
# contract is JSON-only on stdout (hookSpecificOutput.additionalContext)
# — unlike Claude Code's SessionStart, plain text here would break
# parsing, so this script must never print anything but the final JSON
# object.
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

PROJECT_DIR="${GEMINI_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-}}"
if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(json_field cwd)"
  [[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="$(pwd)"
fi

AVO_DIR="$PROJECT_DIR/.avo"
if [[ ! -d "$AVO_DIR" ]]; then
  echo '{}'
  exit 0
fi

SESSION_ID="$(json_field session_id)"
if [[ -n "$SESSION_ID" ]]; then
  ledger_lines=0
  [[ -f "$AVO_DIR/ledger.jsonl" ]] && ledger_lines="$(wc -l < "$AVO_DIR/ledger.jsonl" | tr -d ' ')"
  printf '%s\n' "$ledger_lines" > "/tmp/avo-session-${SESSION_ID}.baseline" 2>/dev/null || true
fi

if [[ -f "$AVO_DIR/lib/common.sh" && -f "$AVO_DIR/lib/ledger.sh" ]]; then
  # shellcheck source=/dev/null
  source "$AVO_DIR/lib/common.sh"
  AVO_DIR="$AVO_DIR" source "$AVO_DIR/lib/ledger.sh" 2>/dev/null
  recent_ledger="$(avo_ledger_last 5 2>/dev/null)"
else
  recent_ledger=""
fi

state_content="$([[ -f "$AVO_DIR/state.md" ]] && cat "$AVO_DIR/state.md" || echo "(sin .avo/state.md)")"
[[ -z "$recent_ledger" ]] && recent_ledger="(ledger vacío — ningún intento registrado todavía)"
deadends_content="$([[ -f "$AVO_DIR/deadends.md" ]] && tail -n 30 "$AVO_DIR/deadends.md" || echo "(sin .avo/deadends.md)")"

context="<avo_memory_context>
  <state>
$(sed 's/^/    /' <<<"$state_content")
  </state>
  <recent_ledger_entries>
$(sed 's/^/    /' <<<"$recent_ledger")
  </recent_ledger_entries>
  <recent_deadends>
$(sed 's/^/    /' <<<"$deadends_content")
  </recent_deadends>
</avo_memory_context>"

if command -v jq >/dev/null 2>&1; then
  jq -n --arg ctx "$context" '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": $ctx}}'
elif command -v python3 >/dev/null 2>&1; then
  python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": sys.stdin.read()}}))' <<<"$context"
else
  # Best-effort minimal escaper if neither tool is available.
  escaped="${context//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  escaped="$(printf '%s' "$escaped" | awk '{printf "%s\\n", $0}')"
  printf '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "%s"}}\n' "$escaped"
fi

exit 0
