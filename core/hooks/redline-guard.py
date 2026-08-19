#!/usr/bin/env python3
"""DevFlow redline guard — PreToolUse hook.

Runs before every Write/Edit/MultiEdit/Bash tool call when the DevFlow
plugin is enabled.  When a ``.devflow/`` directory is present it enforces:

1. **Forbidden files** (.env, keys, secrets)     → deny for every agent and tool
2. **Protected files** (CI/CD, Docker, lockfiles) → deny for every agent
3. **Approval-required files** (package.json, migrations, auth code)
                                                  → ask the user
4. **Directory boundaries**                       → deny if a dev agent
   writes outside its workspace track (server/ vs web/)
5. **Test file protection during development**    → deny edits to existing
   test files unless the current phase is ``testing``
6. **Dangerous Bash commands** (rm -rf /, force push, …) → deny

When no ``.devflow/`` directory exists the hook is completely transparent
(fail-open, exit 0) so normal Claude Code usage is unaffected.

Output contract (stdout):
  allow  → exit 0, no JSON
  deny   → exit 0, JSON with permissionDecision: "deny"
  ask    → exit 0, JSON with permissionDecision: "ask"
All unexpected errors → exit 0 (fail-open).
"""
import json
import os
import sys
from pathlib import Path

# Ensure the hooks/ directory is importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from devflow_guard_common import (
    check_dangerous_command,
    find_project_root,
    get_target_paths,
    infer_track,
    is_devflow_artifact,
    is_test_file,
    is_within_boundary,
    load_context,
    load_redlines,
    path_in_redline_category,
)


# ---------------------------------------------------------------------------
# Decision helpers
# ---------------------------------------------------------------------------

def deny(reason):
    """Emit a deny decision and exit."""
    _emit_decision("deny", reason)


def ask(reason):
    """Emit an ask decision and exit."""
    _emit_decision("ask", reason)


def allow():
    """Allow the tool call (no output)."""
    sys.exit(0)


def _emit_decision(decision, reason):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


# ---------------------------------------------------------------------------
# File operation checks
# ---------------------------------------------------------------------------

def check_file_operation(tool_name, tool_input, project_root, context, redlines):
    """Apply all file-path-based rules.  Calls deny()/ask() on violation."""
    cwd = context.get("cwd", "")
    track = infer_track(cwd, context.get("workspace", {}))
    phase = context.get("current_phase", "")

    targets = get_target_paths(tool_name, tool_input, project_root, cwd)

    for rel_path, abs_path in targets:
        # 1. Forbidden — hard deny for everyone
        if path_in_redline_category(
            rel_path,
            redlines["forbidden"],
            redlines["forbidden_negations"],
        ):
            deny(
                f"[DevFlow Redline] '{rel_path}' is a forbidden file "
                f"(secrets/credentials). Agents must never read or write it."
            )

        # 2. Protected — readable, but hard deny for modifications
        if tool_name != "Read" and path_in_redline_category(
            rel_path,
            redlines["protected"],
            redlines["protected_negations"],
        ):
            deny(
                f"[DevFlow Redline] '{rel_path}' is protected "
                f"(CI/CD, infrastructure, or lock file). "
                f"Agents must not modify it. Report to the Manager if a change "
                f"is genuinely required."
            )

        # 3. Directory boundary — dev agents can only write in their track
        if tool_name != "Read" and track and not is_within_boundary(
            abs_path, context.get("workspace", {}), track, cwd
        ):
            # Allow writes to .devflow/ process artifacts from any agent
            # (scope.yaml, task reports, test reports, contracts, runs/).
            if not is_devflow_artifact(rel_path):
                deny(
                    f"[DevFlow Boundary] The {track} agent cannot write to "
                    f"'{rel_path}' — it is outside the {track} workspace. "
                    f"If this file truly needs changes, report to the Manager."
                )

        # 4. Test file protection during development
        if tool_name != "Read" and phase == "development" and is_test_file(rel_path):
            # Allow creating NEW test files (Write when file doesn't exist),
            # but block editing existing ones so dev agents can't game tests.
            file_exists = os.path.isfile(abs_path)
            if file_exists and tool_name in ("Edit", "MultiEdit"):
                deny(
                    f"[DevFlow Redline] '{rel_path}' is an existing test file. "
                    f"Development agents must not modify tests to make them pass. "
                    f"If the test itself is wrong, report the issue in your "
                    f"task report — the tester agent will evaluate and fix it."
                )
            if file_exists and tool_name == "Write":
                deny(
                    f"[DevFlow Redline] '{rel_path}' already exists and is a "
                    f"test file. Use Edit for targeted changes, or report if "
                    f"the test needs updating."
                )

        # 5. Approval required — ask the user for modifications only
        if tool_name != "Read" and path_in_redline_category(
            rel_path,
            redlines["approval_required"],
            redlines["approval_required_negations"],
        ):
            ask(
                f"[DevFlow Approval] '{rel_path}' requires human approval "
                f"(dependency, migration, auth, or config change). "
                f"Allow this write?"
            )


# ---------------------------------------------------------------------------
# Bash checks
# ---------------------------------------------------------------------------

def check_bash_operation(tool_input, project_root, context, redlines):
    """Apply Bash-specific rules."""
    command = tool_input.get("command", "")
    if not command:
        allow()

    cwd = context.get("cwd", "")

    # 1. Dangerously destructive commands
    danger = check_dangerous_command(command)
    if danger:
        deny(f"[DevFlow Redline] Dangerous command blocked: {danger}")

    # 2. Check shell redirect / tee / sed -i targets against redlines
    targets = get_target_paths("Bash", tool_input, project_root, cwd)
    for rel_path, abs_path in targets:
        if path_in_redline_category(
            rel_path,
            redlines["forbidden"],
            redlines["forbidden_negations"],
        ):
            deny(
                f"[DevFlow Redline] Shell command targets forbidden file "
                f"'{rel_path}'. Use the Write/Edit tools or report to the Manager."
            )
        if path_in_redline_category(
            rel_path,
            redlines["protected"],
            redlines["protected_negations"],
        ):
            deny(
                f"[DevFlow Redline] Shell command targets protected file "
                f"'{rel_path}'. Agents must not modify it via shell either."
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            allow()

        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {}) or {}

        # Only inspect file-writing and Bash tools.
        if tool_name not in ("Read", "Write", "Edit", "MultiEdit", "Bash"):
            allow()

        cwd = data.get("cwd", "") or os.getcwd()
        project_root = find_project_root(cwd)

        # No .devflow directory → DevFlow is not active, stay transparent.
        if not project_root:
            allow()

        # Load DevFlow context and redline rules.
        context = load_context(project_root)
        # The hook input's cwd is the authoritative source for track inference:
        # context.json only records the cwd of the last *dispatched* agent, but
        # the tool may actually run from a subdirectory — or, during parallel
        # backend+frontend dispatch, from the other agent's directory. So we
        # must overwrite with the cwd the platform reports for this call.
        context["cwd"] = cwd

        redlines = load_redlines(project_root)

        if tool_name == "Bash":
            check_bash_operation(tool_input, project_root, context, redlines)
        else:
            check_file_operation(
                tool_name, tool_input, project_root, context, redlines
            )

    except Exception:
        # Fail-open: never block the user due to a hook bug.
        pass

    allow()


if __name__ == "__main__":
    main()
