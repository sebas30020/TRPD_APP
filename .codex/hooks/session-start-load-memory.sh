#!/usr/bin/env bash
# SessionStart hook: injects .avo memory (current state, recent ledger
# entries, recent dead ends) as plain-text context so the agent resumes
# from where the project actually is instead of reconstructing it from
# scratch. Without this hook the memory files exist but nothing reads
# them at session boundaries.
#
# Claude Code adds SessionStart's plain-text stdout to Claude's own
# context (confirmed: this is one of the few events where that happens —
# most hooks' stdout only reaches a debug log). Exit 2 here is NOT a
# blocking signal for SessionStart; only stderr would be shown, and only
# to the human. So this hook only ever exits 0.
set -uo pipefail

INPUT="$(cat)"

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
if [[ -z "$PROJECT_DIR" ]]; then
  if command -v jq >/dev/null 2>&1; then
    PROJECT_DIR="$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)"
  fi
  [[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="$(pwd)"
fi

AVO_DIR="$PROJECT_DIR/.avo"
[[ -d "$AVO_DIR" ]] || exit 0

SESSION_ID=""
if command -v jq >/dev/null 2>&1; then
  SESSION_ID="$(jq -r '.session_id // empty' <<<"$INPUT" 2>/dev/null)"
fi
if [[ -n "$SESSION_ID" ]]; then
  ledger_lines=0
  [[ -f "$AVO_DIR/ledger.jsonl" ]] && ledger_lines="$(wc -l < "$AVO_DIR/ledger.jsonl" | tr -d ' ')"
  printf '%s\n' "$ledger_lines" > "/tmp/avo-session-${SESSION_ID}.baseline" 2>/dev/null || true
fi

if [[ -x "$AVO_DIR/lib/ledger.sh" || -f "$AVO_DIR/lib/ledger.sh" ]]; then
  # shellcheck source=/dev/null
  AVO_DIR="$AVO_DIR" source "$AVO_DIR/lib/ledger.sh" 2>/dev/null
  recent_ledger="$(avo_ledger_last 5 2>/dev/null)"
else
  recent_ledger="(no se pudo cargar .avo/lib/ledger.sh)"
fi

echo "<avo_memory_context>"
echo "  <state>"
if [[ -f "$AVO_DIR/state.md" ]]; then
  sed 's/^/    /' "$AVO_DIR/state.md"
else
  echo "    (sin .avo/state.md)"
fi
echo "  </state>"
echo "  <recent_ledger_entries>"
if [[ -n "$recent_ledger" ]]; then
  sed 's/^/    /' <<<"$recent_ledger"
else
  echo "    (ledger vacío — ningún intento registrado todavía)"
fi
echo "  </recent_ledger_entries>"
echo "  <recent_deadends>"
if [[ -f "$AVO_DIR/deadends.md" ]]; then
  tail -n 30 "$AVO_DIR/deadends.md" | sed 's/^/    /'
else
  echo "    (sin .avo/deadends.md)"
fi
echo "  </recent_deadends>"
echo "</avo_memory_context>"

exit 0
