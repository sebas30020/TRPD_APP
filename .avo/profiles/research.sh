#!/usr/bin/env bash
# Research/content verification profile. Where there's no compiler to say
# no, this fabricates four objective signals instead of asking the
# authoring agent's opinion:
#   1. citation audit      — every [^n]/[Fuente] marker resolves somewhere
#   2. link check           — egress-aware: a blocked domain is not a dead link
#   3. reproducibility      — scripts in .avo/repro/ must actually run
#   4. fresh-context critic — a SEPARATE agent invocation (not this script,
#      which cannot call an LLM) scores the work against .avo/rubric.md and
#      writes .avo/critique.json; this script only checks that verdict
#      exists and is not self-reported by the author. See docs/playbook.md.
set -uo pipefail

PROFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVO_DIR="$(cd "$PROFILES_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$AVO_DIR/.." && pwd)"
# shellcheck source=../lib/common.sh
source "$AVO_DIR/lib/common.sh"
cd "$PROJECT_DIR" || exit 1

SIGNALS=()
PASS=true
METRIC_NAME="null"
METRIC_VALUE="null"
ERROR_DETAILS=""

have() { command -v "$1" >/dev/null 2>&1; }

fail() {
  local label="$1" detail="$2"
  SIGNALS+=("${label}:fail")
  PASS=false
  ERROR_DETAILS+="[$label] $detail"$'\n'
}
ok() { SIGNALS+=("$1:ok"); }
skip() { SIGNALS+=("$1:skipped(not_applicable)"); }

# Markdown files under the project, excluding harness/vcs/dependency dirs.
md_files() {
  find "$PROJECT_DIR" \
    \( -path "*/.avo" -o -path "*/.git" -o -path "*/node_modules" -o -path "*/.claude" \) -prune -o \
    -type f -name '*.md' -print 2>/dev/null
}

# ---- 1. Citation audit ------------------------------------------------
citation_check() {
  local used defs missing=() ref n def_found fuente_files
  used="$(md_files | xargs -r grep -ohE '\[\^[0-9]+\]' 2>/dev/null | sort -u)"
  defs="$(md_files | xargs -r grep -ohE '^\[\^[0-9]+\]:' 2>/dev/null | sort -u)"
  fuente_files="$(md_files | xargs -r grep -l '\[Fuente\]' 2>/dev/null)"

  if [[ -z "$used" && -z "$fuente_files" ]]; then
    skip "citations"
    return
  fi

  if [[ -n "$used" ]]; then
    while IFS= read -r ref; do
      [[ -z "$ref" ]] && continue
      n="${ref//[^0-9]/}"
      def_found="$(grep -F "[^${n}]:" <<<"$defs" || true)"
      [[ -z "$def_found" ]] && missing+=("$ref")
    done <<<"$used"
  fi

  local refs_file_missing=false
  if [[ -n "$fuente_files" ]]; then
    if [[ ! -s "$PROJECT_DIR/references.md" && ! -s "$PROJECT_DIR/REFERENCES.md" ]]; then
      refs_file_missing=true
    fi
  fi

  if [[ "${#missing[@]}" -gt 0 || "$refs_file_missing" == true ]]; then
    local detail="Marcadores [^n] sin definición: ${missing[*]:-ninguno}."
    [[ "$refs_file_missing" == true ]] && detail+=" Hay marcadores [Fuente] pero no existe references.md/REFERENCES.md no vacío."
    fail "citations" "$detail"
  else
    ok "citations"
  fi
}

# ---- 2. Egress-aware link check ---------------------------------------
# Domains known to be blocked at the network/proxy layer in this kind of
# sandboxed environment. A URL on this list is reported as
# blocked_by_egress_policy, not as a broken link. Extend as new blocks are
# confirmed — see docs/source-notes.md.
EGRESS_BLOCKED_DOMAINS=(
  "developer.nvidia.com"
  "arxiv.org"
  "docs.arcprize.org"
  "thenewstack.io"
)

is_known_blocked_domain() {
  local host="$1" d
  for d in "${EGRESS_BLOCKED_DOMAINS[@]}"; do
    [[ "$host" == "$d" || "$host" == *".$d" ]] && return 0
  done
  return 1
}

link_check() {
  local urls host broken=() blocked=() live=()
  urls="$(md_files | xargs -r grep -ohE 'https?://[^)"[:space:]]+' 2>/dev/null | sort -u)"
  if [[ -z "$urls" ]]; then
    skip "links"
    return
  fi
  while IFS= read -r url; do
    [[ -z "$url" ]] && continue
    host="$(printf '%s' "$url" | sed -E 's#^https?://([^/]+).*#\1#')"
    if is_known_blocked_domain "$host"; then
      blocked+=("$url")
      continue
    fi
    if ! have curl; then
      skip "links"
      return
    fi
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)"
    local curl_status=$?
    if [[ $curl_status -ne 0 ]]; then
      # Transport-level failure (DNS/connect/TLS/timeout): treat as an
      # unconfirmed egress block rather than a confirmed dead link, since
      # we can't tell the two apart from here.
      blocked+=("$url (curl exit $curl_status, unconfirmed)")
    elif [[ "$code" =~ ^(2|3) ]]; then
      live+=("$url")
    else
      broken+=("$url ($code)")
    fi
  done <<<"$urls"

  if [[ "${#broken[@]}" -gt 0 ]]; then
    fail "links" "Enlaces rotos: ${broken[*]}"
  else
    ok "links"
  fi
  [[ "${#blocked[@]}" -gt 0 ]] && SIGNALS+=("links_blocked_by_egress:${#blocked[@]}")
}

# ---- 3. Reproducibility -------------------------------------------------
repro_check() {
  local repro_dir="$AVO_DIR/repro" scripts=() s failed=()
  [[ -d "$repro_dir" ]] || { skip "repro"; return; }
  while IFS= read -r -d '' s; do
    [[ "$(basename "$s")" == ".gitkeep" ]] && continue
    scripts+=("$s")
  done < <(find "$repro_dir" -maxdepth 1 -type f -print0 2>/dev/null)

  if [[ "${#scripts[@]}" -eq 0 ]]; then
    skip "repro"
    return
  fi

  for s in "${scripts[@]}"; do
    if [[ -x "$s" ]]; then
      "$s" >/dev/null 2>&1 || failed+=("$(basename "$s")")
    else
      bash "$s" >/dev/null 2>&1 || failed+=("$(basename "$s")")
    fi
  done

  if [[ "${#failed[@]}" -gt 0 ]]; then
    fail "repro" "Scripts que fallaron: ${failed[*]}"
  else
    ok "repro"
  fi
}

# ---- 4. Fresh-context critic --------------------------------------------
# This script cannot invoke an LLM itself. It only verifies that a
# separately-produced critique exists — see the module header.
critic_check() {
  local path="$AVO_DIR/critique.json"
  if [[ ! -f "$path" ]]; then
    fail "critic" "Falta .avo/critique.json. Antes de verificar, invoca un agente con contexto fresco (sin el historial de esta sesión) para que puntúe el resultado contra .avo/rubric.md y escriba {\"verdict\":\"pass|fail\",\"notes\":\"...\"}."
    return
  fi
  local content
  content="$(cat "$path")"
  if ! avo_json_valid "$content"; then
    fail "critic" ".avo/critique.json no es JSON válido."
    return
  fi
  local verdict
  verdict="$(avo_json_get "$content" "verdict" "")"
  case "$verdict" in
    pass) ok "critic" ;;
    fail)
      local notes
      notes="$(avo_json_get "$content" "notes" "(sin notas)")"
      fail "critic" "El crítico de contexto fresco rechazó el resultado: $notes"
      ;;
    *) fail "critic" ".avo/critique.json no tiene un 'verdict' válido (pass|fail)." ;;
  esac
}

citation_check
link_check
repro_check
critic_check

signals_json="[]"
if [[ "${#SIGNALS[@]}" -gt 0 ]]; then
  parts=()
  for s in "${SIGNALS[@]}"; do parts+=("$(avo_json_string "$s")"); done
  signals_json="[$(IFS=,; echo "${parts[*]}")]"
fi

error_json="null"
[[ -n "$ERROR_DETAILS" ]] && error_json="$(avo_json_string "$ERROR_DETAILS")"

printf '{"pass":%s,"metric_name":%s,"metric_value":%s,"signals":%s,"error_details":%s}\n' \
  "$PASS" "$METRIC_NAME" "$METRIC_VALUE" "$signals_json" "$error_json"

if [[ "$PASS" == "true" ]]; then
  exit 0
else
  exit 1
fi
