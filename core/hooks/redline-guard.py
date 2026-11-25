#!/usr/bin/env python3
"""DevFlow redline guard — PreToolUse hook.

Runs before every Write/Edit/MultiEdit/Bash tool call when the DevFlow
plugin is enabled.  When a ``.devflow/`` directory is present it enforces:

1. **Forbidden files** (.env, keys, secrets)     → deny for every agent and tool
2. **Protected files** (CI/CD, Docker, lockfiles) → deny for every agent
3. **Approval-required files** (package.json, migrations, auth code)
                                                  → ask the user
4. **Directory boundary** — writes must stay inside the project root
   (the session's launch directory); drilling down is allowed, going up or
   outside is denied.
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
    _extract_shell_read_targets,
    check_dangerous_command,
    content_carries_credential,
    content_was_inspectable,
    find_project_root,
    get_target_paths,
    is_devflow_artifact,
    is_devflow_protected,
    is_git_commit,
    is_test_file,
    is_within_boundary,
    load_context,
    load_redlines,
    path_in_redline_category,
    task_needs_archive,
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

        # 2b. Config — neither read nor write. A configuration file carries
        #     credentials (reading leaks what the forbidden rules protect) and
        #     endpoints (writing redirects where those credentials are sent).
        #     Stricter than ``protected`` on purpose: read is denied too.
        if path_in_redline_category(
            rel_path,
            redlines["config_protected"],
            redlines["config_protected_negations"],
        ):
            deny(
                f"[DevFlow Redline] '{rel_path}' is configuration and cannot be "
                f"read or modified by agents. Ask the user for the value you "
                f"need, or have them make the change."
            )

        # 3. DevFlow-protected files — anything under .devflow/ that is not an agent
        #    artifact (redlines.yaml, task.yaml, project.yaml, rules/, contracts).
        #    The boundary rule below allows everything inside the project root,
        #    so this dedicated check stops an agent editing its own guardrails.
        if tool_name != "Read" and is_devflow_protected(rel_path):
            deny(
                f"[DevFlow Redline] '{rel_path}' is DevFlow configuration and "
                f"cannot be modified by agents. Report to the Manager if a change "
                f"is genuinely required."
            )

        # 4. Directory boundary - agents may only write inside the project
        # root (the session's launch directory), drilling down but never up.
        # A workspace may span several repositories, so no per-repo track
        # gating applies. Writes to .devflow/ process artifacts stay allowed
        # even when they resolve outside the root (worktree mapping).
        if (
            tool_name != "Read"
            and not is_within_boundary(abs_path, project_root, cwd)
            and not is_devflow_artifact(rel_path)
        ):
            deny(
                f"[DevFlow Boundary] Cannot write to '{rel_path}' - it is outside "
                f"the project root. Agents work within the launch directory only; "
                f"if this file truly needs changes, report to the Manager."
            )

        # 5. Test file protection during development
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

        # 6. Approval required — only when the write actually looks
        #    credential-bearing. A path match alone is too coarse: bumping a
        #    timeout in config/app.yaml or refactoring an auth helper is
        #    routine work, and asking on every such edit is what makes the
        #    guard feel like a brake. When no content was inspectable (Edit
        #    carries only a snippet), keep the conservative ask.
        if tool_name != "Read" and path_in_redline_category(
            rel_path,
            redlines["approval_required"],
            redlines["approval_required_negations"],
        ):
            if content_carries_credential(tool_name, tool_input):
                ask(
                    f"[DevFlow Approval] '{rel_path}' is being written with "
                    f"credential-looking content (dependency, migration, auth, "
                    f"or config change). Allow this write?"
                )
            elif not content_was_inspectable(tool_name, tool_input):
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

    # 2. Delivery archive gate: in the delivery phase, refuse to commit until
    #    the task's process artifacts have been published to .devflow/tasks/.
    #    The archive index (README.md) is written as the terminal step of
    #    ``artifact_publish.publish``, so its absence means the publish step
    #    was skipped and the artifacts would otherwise be lost when the
    #    worktree is cleaned up.
    phase = context.get("current_phase", "")
    if phase == "delivery" and is_git_commit(command) and task_needs_archive(project_root):
        deny(
            "[DevFlow Redline] Delivery blocked: task artifacts are not yet "
            "archived. Run `artifact_publish.py publish` first so PRD / scope / "
            "reports / contracts land in .devflow/tasks/<task-id>/ before committing."
        )

    # 3. Check shell redirect / tee / sed -i targets against redlines
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

        # 3b. DevFlow-protected files — same rule as the file tools. Without
        #     this, ``echo > .devflow/redlines.yaml`` would rewrite the guard
        #     while ``Write`` to the same file is denied.
        if is_devflow_protected(rel_path):
            deny(
                f"[DevFlow Redline] Shell command targets DevFlow configuration "
                f"'{rel_path}'. Agents may not modify it via shell either."
            )

        # 4. Directory boundary — a shell write outside the project root must
        #    be denied just like the Write tool's. ``is_within_boundary``
        #    exempts user-level state (``~/.claude``, Memorant) and worktree
        #    mapping; DevFlow process artifacts are not shell-writable outside
        #    the root, matching the file-tool behaviour.
        if not is_within_boundary(abs_path, project_root, cwd):
            deny(
                f"[DevFlow Boundary] Shell command writes '{rel_path}', which is "
                f"outside the project root. Agents work within the launch "
                f"directory only; report to the Manager if this is needed."
            )

    # 4. Config is refused on read as well, so a shell reader that names a
    #    config path has to be checked too — otherwise ``cat config/app.yaml``
    #    walks around the file-tool rule.
    for rel_path, _abs_path in _extract_shell_read_targets(command, project_root, cwd):
        if path_in_redline_category(
            rel_path,
            redlines["config_protected"],
            redlines["config_protected_negations"],
        ):
            deny(
                f"[DevFlow Redline] Shell command reads configuration file "
                f"'{rel_path}'. Configuration cannot be read or modified by "
                f"agents. Ask the user for the value you need."
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
        # The hook's per-call cwd locates relative tool paths; the project
        # root itself comes from the fixed launch directory (CLAUDE_PROJECT_DIR)
        # so it does not drift when the agent cd's.
        context["cwd"] = cwd

        redlines = load_redlines(project_root)

        if tool_name == "Bash":
            check_bash_operation(tool_input, project_root, context, redlines)
        else:
            check_file_operation(tool_name, tool_input, project_root, context, redlines)

    except Exception:
        # Fail-open: never block the user due to a hook bug.
        pass

    allow()


if __name__ == "__main__":
    main()
