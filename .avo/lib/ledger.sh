#!/usr/bin/env bash
# CRUD helpers over .avo/ledger.jsonl, the append-only attempt log that
# gives each ledger entry a lineage (its `parent`) the way AVO tracks a
# candidate's lineage. One JSON object per line; never rewritten in place.

AVO_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$AVO_LIB_DIR/common.sh"

avo_ledger_path() {
  echo "${AVO_DIR:-.avo}/ledger.jsonl"
}

# avo_ledger_append <json-line>
# Refuses to append anything that isn't valid JSON on one line, since a
# corrupt ledger silently breaks every downstream reader (resume, stats,
# a future stagnation supervisor).
avo_ledger_append() {
  local line="$1" path
  path="$(avo_ledger_path)"
  if [[ "$line" == *$'\n'* ]]; then
    echo "avo: ledger entries must be single-line JSON" >&2
    return 1
  fi
  if ! avo_json_valid "$line"; then
    echo "avo: refusing to append invalid JSON to ledger" >&2
    return 1
  fi
  mkdir -p "$(dirname "$path")"
  printf '%s\n' "$line" >> "$path"
}

# avo_ledger_last <n>
avo_ledger_last() {
  local n="${1:-5}" path
  path="$(avo_ledger_path)"
  [[ -f "$path" ]] || return 0
  tail -n "$n" "$path"
}

# avo_ledger_count
avo_ledger_count() {
  local path
  path="$(avo_ledger_path)"
  if [[ -f "$path" ]]; then
    wc -l < "$path" | tr -d ' '
  else
    echo 0
  fi
}

# avo_ledger_filter_field <field> <value>
avo_ledger_filter_field() {
  local field="$1" value="$2" path
  path="$(avo_ledger_path)"
  [[ -f "$path" ]] || return 0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    [[ "$(avo_json_get "$line" "$field" "")" == "$value" ]] && printf '%s\n' "$line"
  done < "$path"
}

avo_ledger_filter_verdict() { avo_ledger_filter_field "verdict" "$1"; }
avo_ledger_filter_tag() { avo_ledger_filter_field "approach_tag" "$1"; }

avo_ledger_stats() {
  local total commits rejects parks
  total="$(avo_ledger_count)"
  commits="$(avo_ledger_filter_verdict commit | grep -c . || true)"
  rejects="$(avo_ledger_filter_verdict reject | grep -c . || true)"
  parks="$(avo_ledger_filter_verdict park | grep -c . || true)"
  printf 'total=%s commit=%s reject=%s park=%s\n' "$total" "$commits" "$rejects" "$parks"
}

# avo_ledger_last_id — id of the most recent entry, for use as `parent`.
avo_ledger_last_id() {
  local last
  last="$(avo_ledger_last 1)"
  [[ -n "$last" ]] && avo_json_get "$last" "id" ""
}
