#!/bin/bash
# Fail-open shim for the DevFlow hook handler.
# Delegates to devflow_hook.py in the same directory. Never blocks
# the user on errors: any failure emits empty JSON and exits 0.
set -uo pipefail

emit_empty() {
  printf '{}\n'
  exit 0
}

INPUT="$(mktemp 2>/dev/null)" || emit_empty
OUTPUT="$(mktemp 2>/dev/null)" || { rm -f "$INPUT"; emit_empty; }
cleanup() { rm -f "$INPUT" "$OUTPUT"; }
trap cleanup EXIT
cat > "$INPUT" 2>/dev/null || emit_empty

command -v python3 >/dev/null 2>&1 || emit_empty

# Resolve the Python handler next to this script, with a fallback to
# CLAUDE_PLUGIN_ROOT/hooks when the plugin is installed.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null)" || SCRIPT_DIR=""
HOOK_PY="${SCRIPT_DIR}/devflow_hook.py"
if [[ ! -f "$HOOK_PY" && -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
  HOOK_PY="${CLAUDE_PLUGIN_ROOT}/hooks/devflow_hook.py"
fi
[[ -f "$HOOK_PY" ]] || emit_empty

# -B -S keep the run offline / venv-free; the hook needs no third-party deps.
CMD=(python3 -B -S "$HOOK_PY")

python3 - "${DEVFLOW_HOOK_TIMEOUT_SECONDS:-5.0}" "$INPUT" "$OUTPUT" \
  "${CMD[@]}" <<'PY' || emit_empty
import subprocess
import sys

timeout, input_path, output_path, *command = sys.argv[1:]
try:
    seconds = float(timeout)
    if not 0.1 <= seconds <= 30:
        raise ValueError("timeout outside safe range")
    with open(input_path, "rb") as stdin, open(output_path, "wb") as stdout:
        completed = subprocess.run(
            command,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            timeout=seconds,
            check=False,
        )
    if completed.returncode != 0:
        raise SystemExit(1)
except (OSError, subprocess.TimeoutExpired, ValueError):
    raise SystemExit(1)
PY

SIZE="$(wc -c < "$OUTPUT" 2>/dev/null | tr -d ' ')"
[[ "$SIZE" =~ ^[0-9]+$ && "$SIZE" -le 10000 && "$SIZE" -gt 0 ]] || emit_empty

# PreCompact reaches the model as plain text on stdout; other hooks
# must emit valid JSON in hookSpecificOutput.additionalContext.
HOOK_EVENT="$(python3 -B -S -c '
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("hook_event_name") or "")
except Exception:
    print("")
' "$INPUT" 2>/dev/null)"

if [[ "$HOOK_EVENT" == "PreCompact" ]]; then
  cat "$OUTPUT" 2>/dev/null || emit_empty
  exit 0
fi

python3 -c 'import json,sys; json.load(sys.stdin)' < "$OUTPUT" >/dev/null 2>&1 \
  || emit_empty
cat "$OUTPUT" 2>/dev/null || emit_empty
exit 0
