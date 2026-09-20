#!/usr/bin/env bash
# Validates the two contracts the harness depends on: verify.sh's JSON
# output, and a ledger entry's required fields. Kept separate from
# ledger.sh so avo-init and the hooks can validate without pulling in
# ledger read/write helpers.

AVO_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$AVO_LIB_DIR/common.sh"

# avo_validate_verify_output <json>
# Required: boolean `pass`. `signals` should be an array but its absence
# is a warning, not a hard failure — a first-run verify.sh stub may not
# have real signals yet.
avo_validate_verify_output() {
  local json="$1"
  if ! avo_json_valid "$json"; then
    echo "avo: verify output is not valid JSON" >&2
    return 1
  fi
  local pass
  pass="$(avo_json_get "$json" "pass" "__missing__")"
  if [[ "$pass" != "true" && "$pass" != "false" ]]; then
    echo "avo: verify output missing boolean 'pass' field" >&2
    return 1
  fi
  return 0
}

# avo_validate_ledger_entry <json-line>
# Required: id, ts, kind, approach_tag, and verdict in {commit,reject,park}.
avo_validate_ledger_entry() {
  local json="$1"
  local -a missing=()
  if ! avo_json_valid "$json"; then
    echo "avo: ledger entry is not valid JSON" >&2
    return 1
  fi
  local field value
  for field in id ts kind approach_tag; do
    value="$(avo_json_get "$json" "$field" "__missing__")"
    [[ "$value" == "__missing__" || -z "$value" ]] && missing+=("$field")
  done
  local verdict
  verdict="$(avo_json_get "$json" "verdict" "")"
  case "$verdict" in
    commit|reject|park) ;;
    *) missing+=("verdict(commit|reject|park)") ;;
  esac
  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "avo: ledger entry missing/invalid fields: ${missing[*]}" >&2
    return 1
  fi
  return 0
}
