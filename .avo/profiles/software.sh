#!/usr/bin/env bash
# Software verification profile for TRPD_APP:
# Runs import smoke tests for app.py and calibrar_app, and executes tests/ via pytest in .venv.
set -uo pipefail

PROFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVO_DIR="$(cd "$PROFILES_DIR/.." && pwd)"
PROJECT_DIR="$(cd "$AVO_DIR/.." && pwd)"
# shellcheck source=../lib/common.sh
source "$AVO_DIR/lib/common.sh"
cd "$PROJECT_DIR" || exit 1

PYTHON="${TRPD_PYTHON:-$PROJECT_DIR/.venv/Scripts/python.exe}"
if [[ ! -x "$PYTHON" ]]; then
  cat <<EOF
{"pass":false,"metric_name":"entorno","metric_value":1,"signals":["python_env:fail"],"error_details":"No se encontro el interprete de Python en $PYTHON. No degradar al Python global."}
EOF
  exit 1
fi

SIGNALS=()
PASS=true
METRIC_NAME="tests_fallidos"
METRIC_VALUE="0"
ERROR_DETAILS=""

run_check() {
  local label="$1"; shift
  local out status
  out="$("$@" 2>&1)"
  status=$?
  if [[ $status -eq 0 ]]; then
    SIGNALS+=("${label}:ok")
  else
    SIGNALS+=("${label}:fail(exit ${status})")
    PASS=false
    ERROR_DETAILS+="[$label]"$'\n'"$(tail -n 25 <<<"$out")"$'\n'
  fi
  return $status
}

# 1. Smoke test app.py import
run_check "import_app" "$PYTHON" -c "import app"

# 2. Smoke test calibrar_app if main.py exists
if [[ -f "$PROJECT_DIR/calibrar_app/main.py" ]]; then
  run_check "import_calibrar_app" "$PYTHON" -c "import sys; sys.path.insert(0,'calibrar_app'); import main"
fi

# 3. Run pytest if tests/ exists
if [[ -d "$PROJECT_DIR/tests" ]]; then
  test_out="$("$PYTHON" -m pytest -q tests/ 2>&1)"
  test_status=$?
  if [[ $test_status -eq 0 ]]; then
    SIGNALS+=("tests:ok")
    METRIC_VALUE="0"
  else
    SIGNALS+=("tests:fail(exit ${test_status})")
    PASS=false
    # Try to parse failed tests count or default to 1
    failed_count=$(grep -oE '[0-9]+ failed' <<<"$test_out" | awk '{print $1}' | head -n 1)
    if [[ -n "$failed_count" ]]; then
      METRIC_VALUE="$failed_count"
    else
      METRIC_VALUE="1"
    fi
    ERROR_DETAILS+="[tests]"$'\n'"$(tail -n 30 <<<"$test_out")"$'\n'
  fi
else
  SIGNALS+=("tests:no_tests_dir")
fi

signals_json="[]"
if [[ "${#SIGNALS[@]}" -gt 0 ]]; then
  parts=()
  for s in "${SIGNALS[@]}"; do parts+=("$(avo_json_string "$s")"); done
  signals_json="[$(IFS=,; echo "${parts[*]}")]"
fi

error_json="null"
[[ -n "$ERROR_DETAILS" ]] && error_json="$(avo_json_string "$ERROR_DETAILS")"

printf '{"pass":%s,"metric_name":%s,"metric_value":%s,"signals":%s,"error_details":%s}\n' \
  "$PASS" "\"$METRIC_NAME\"" "$METRIC_VALUE" "$signals_json" "$error_json"

if [[ "$PASS" == "true" ]]; then
  exit 0
else
  exit 1
fi
