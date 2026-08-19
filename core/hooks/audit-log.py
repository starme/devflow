#!/usr/bin/env python3
"""DevFlow audit logger — PostToolUse hook.

After every successful Write/Edit/MultiEdit/Bash tool call, appends a
single TSV-style line to ``.devflow/runs/<run_id>/audit.log``:

    2026-08-18T14:50:22 | agent | phase | tool | target | detail

- For file tools the target is the relative file path.
- For Bash the target is the first 120 characters of the command.

When DevFlow is not active (no ``.devflow/``) or no run is in progress the
hook does nothing.  It never blocks the user.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from devflow_guard_common import (
    find_project_root,
    get_target_paths,
    load_context,
)


MAX_DETAIL = 200


def _truncate(text, limit=MAX_DETAIL):
    text = text.replace("\n", " ").replace("\r", " ").replace("|", "/")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def append_log(project_root, context, tool_name, tool_input, cwd=""):
    """Append one audit line."""
    run_id = context.get("run_id", "")
    if not run_id:
        return

    log_dir = project_root / ".devflow" / "runs" / run_id
    log_file = log_dir / "audit.log"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    agent = context.get("current_agent", "unknown")
    phase = context.get("current_phase", "unknown")
    timestamp = datetime.now().isoformat(timespec="seconds")

    if tool_name in ("Write", "Edit", "MultiEdit"):
        targets = get_target_paths(tool_name, tool_input, project_root, cwd)
        if targets:
            target = targets[0][0]  # relative path
        else:
            target = tool_input.get("file_path", "?")
        detail = tool_name
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        target = "bash"
        detail = _truncate(cmd)
    else:
        target = "?"
        detail = tool_name

    line = f"{timestamp} | {agent} | {phase} | {tool_name} | {target} | {detail}\n"

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            sys.exit(0)

        tool_name = data.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit", "Bash"):
            sys.exit(0)

        tool_input = data.get("tool_input", {}) or {}
        cwd = data.get("cwd", "") or os.getcwd()

        project_root = find_project_root(cwd)
        if not project_root:
            sys.exit(0)

        context = load_context(project_root)
        if not context.get("run_id"):
            sys.exit(0)

        context["cwd"] = cwd
        append_log(project_root, context, tool_name, tool_input, cwd)

    except Exception:
        # Audit logging must never interfere with the workflow.
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
