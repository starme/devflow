#!/usr/bin/env python3
"""DevFlow hook handler — processes Claude Code hook events.

Fail-open: any exception results in empty JSON output so the user
is never blocked.

v2 (ADR-0005): hooks only *inform*, never *block*. The Stop event is no
longer registered — the model is trusted to continue working to the next
Gate on its own. SessionStart injects task context, UserPromptSubmit hints
when a Gate is waiting for the user, PreCompact preserves task state.
"""

import glob
import json
import os
import re
import sys
from pathlib import Path


def _version_key(path):
    """Parse a trailing ``1.2.3``-style directory name for newest-cache picks."""
    name = os.path.basename(str(path).rstrip(os.sep))
    parts = []
    for bit in name.split("."):
        if bit.isdigit():
            parts.append(int(bit))
        else:
            return (0,)
    return tuple(parts) if parts else (0,)


def _newest_dir(paths):
    """Pick the newest existing directory: version name first, then mtime."""
    dirs = [p for p in paths if os.path.isdir(p)]
    if not dirs:
        return None
    return max(dirs, key=lambda p: (_version_key(p), os.path.getmtime(p)))


def find_plugin_root():
    """Locate the devflow plugin directory.

    Checks in order:
      1. CLAUDE_PLUGIN_ROOT environment variable
      2. ~/.claude/plugins/cache/*/devflow/*/ (newest version/mtime)
      3. ~/.claude/plugins/marketplaces/devflow-marketplace/
      4. ~/.claude/plugins/marketplaces/*/devflow/ (newest mtime)
      5. This script's parent directory's parent (hooks/..)
    Returns path as string or None.
    """
    try:
        env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if env_root and os.path.isdir(env_root):
            return env_root
    except Exception:
        pass

    try:
        home = Path.home()
        pattern = str(home / ".claude" / "plugins" / "cache" / "*" / "devflow" / "*")
        newest = _newest_dir(glob.glob(pattern))
        if newest:
            return newest
    except Exception:
        pass

    try:
        home = Path.home()
        mp_direct = home / ".claude" / "plugins" / "marketplaces" / "devflow-marketplace"
        if mp_direct.is_dir():
            return str(mp_direct)
    except Exception:
        pass

    try:
        home = Path.home()
        pattern = str(home / ".claude" / "plugins" / "marketplaces" / "*" / "devflow")
        newest = _newest_dir(glob.glob(pattern))
        if newest:
            return newest
    except Exception:
        pass

    try:
        script_dir = Path(__file__).resolve().parent
        plugin_root = script_dir.parent
        if plugin_root.is_dir():
            return str(plugin_root)
    except Exception:
        pass

    return None


def get_plugin_root():
    """Public accessor for the plugin root directory (for orchestrator skill)."""
    return find_plugin_root()


def check_rules_installed():
    """Check if ~/.claude/rules/engineering.md exists."""
    try:
        rules_file = Path.home() / ".claude" / "rules" / "engineering.md"
        return rules_file.exists()
    except Exception:
        return False


def memorant_available():
    """Check if Memorant plugin is installed by reading installed_plugins.json.

    Supports both v1 (top-level plugin name keys) and v2 (plugins dict with
    "name@marketplace" keys) formats.
    """
    try:
        installed_file = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
        if not installed_file.exists():
            return False
        content = installed_file.read_text(encoding="utf-8", errors="replace")
        data = json.loads(content)
        if not isinstance(data, dict):
            return False
        # v2 format: {"version": 2, "plugins": {"memorant@marketplace": [...]}}
        plugins = data.get("plugins")
        if isinstance(plugins, dict):
            return any(k.split("@", 1)[0] == "memorant" for k in plugins)
        # v1 format: {"memorant": [...], ...}
        return "memorant" in data
    except Exception:
        return False


def _workspace_resolver():
    """Load the shared project-root resolver from ``core/workspace.py``.

    The hook runs with ``python3 -B -S`` from the plugin's ``hooks/`` directory,
    so ``core`` is not on ``sys.path``.  Read the resolver by file location;
    on any failure return ``None`` and let ``find_manifest`` fall back to its
    own local check, so the hook never breaks the session.
    """
    try:
        import importlib.util

        core = Path(__file__).resolve().parent.parent / "core" / "workspace.py"
        if not core.is_file():
            plugin_root = find_plugin_root()
            if not plugin_root:
                return None
            core = Path(plugin_root) / "core" / "workspace.py"
        spec = importlib.util.spec_from_file_location("devflow_core_workspace", core)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def find_manifest(cwd=None):
    """Return ``(state_file, project_root)`` for the current session.

    The root is the single authoritative launch directory — ``CLAUDE_PROJECT_DIR``
    when set (fixed at session start; the stdin ``cwd`` drifts after a ``cd``),
    otherwise the payload ``cwd``.  It is a root only when it owns ``.devflow/``
    itself; when it does not, the session is uninitialised and NO other
    directory (a child, an ancestor, or the process cwd) may stand in.  Lookup
    order inside that root is ``task.yaml`` (per-task phase), ``project.yaml``,
    then legacy ``manifest.yaml``; migration stays in ``/devflow init`` /
    ``next``.
    """
    try:
        module = _workspace_resolver()
        if module is not None:
            root = module.resolve_session_project_root(cwd)
        else:
            raw = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
            start = Path(raw).resolve()
            root = start if (start / ".devflow").is_dir() else None
        # The launch directory is authoritative: if it is uninitialised, no
        # other directory (payload cwd, process cwd, a child) may stand in.
        if root is None:
            return None, None
        devflow = root / ".devflow"
        for name in ("task.yaml", "project.yaml", "manifest.yaml"):
            candidate = devflow / name
            if candidate.is_file():
                return candidate, root
        return None, None
    except Exception:
        pass
    return None, None


def read_manifest_phase(manifest_path):
    """Extract current_phase from manifest.yaml without requiring yaml module."""
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("current_phase:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return "unknown"


def read_task_phase(task_path):
    """Extract ``task.current_phase`` from a ``task.yaml`` state file.

    Unlike the legacy manifest, task.yaml nests ``current_phase`` under the
    ``task:`` section, so a naive top-level ``current_phase:`` scan misses it.
    """
    try:
        content = task_path.read_text(encoding="utf-8", errors="replace")
        in_task = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped == "task:":
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(":"):
                break
            if in_task and stripped.startswith("current_phase:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return "unknown"


def read_state_phase(state_path):
    """Read the current phase from whichever state file *state_path* points at.

    ``task.yaml`` (isolated worktree) and ``manifest.yaml``/``project.yaml``
    (legacy) store the phase in different positions, so dispatch on filename.
    """
    name = state_path.name
    if name == "task.yaml":
        return read_task_phase(state_path)
    return read_manifest_phase(state_path)


def read_work_type(state_path):
    """Read the work type (feature/bugfix/chore) from the state file.

    ``task.yaml`` stores it nested as ``task.kind``; the legacy manifest uses
    the top-level ``work_type:`` field. ``project.yaml`` carries no work type
    (it is project-level config), so it falls back to the neutral ``—``.
    """
    name = state_path.name
    if name == "task.yaml":
        return read_task_kind(state_path) or "—"
    return read_manifest_field(state_path, "work_type:") or "—"


def read_task_kind(task_path):
    """Extract ``task.kind`` from a ``task.yaml`` state file.

    Mirrors :func:`read_task_phase` — ``kind`` nests under the ``task:``
    section, so a top-level scan would miss it.
    """
    try:
        content = task_path.read_text(encoding="utf-8", errors="replace")
        in_task = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped == "task:":
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(":"):
                break
            if in_task and stripped.startswith("kind:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return None


def read_manifest_field(manifest_path, field):
    """Extract a top-level or project-level string field from manifest.yaml."""
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(field + ":"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return None


def read_tasks_summary(manifest_path, phase):
    """Count completed/total tasks for development phase.

    Parses the tasks list in the manifest, counting items by status field.
    Returns '3/5 tasks' or empty string.
    """
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        in_tasks = False
        tasks_indent = None
        completed = 0
        total = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("tasks:"):
                in_tasks = True
                tasks_indent = len(line) - len(line.lstrip())
                continue
            if in_tasks:
                current_indent = len(line) - len(line.lstrip())
                if stripped and current_indent <= tasks_indent and not stripped.startswith("-"):
                    break
                if stripped.startswith("- id:"):
                    total += 1
                if stripped.startswith("status: completed") or stripped.endswith(
                    "status: completed"
                ):
                    completed += 1
        if total > 0:
            return f"{completed}/{total} tasks"
    except Exception:
        pass
    return ""


def emit(context, event_name="SessionStart"):
    """Emit JSON hook output.

    Claude Code requires hookEventName inside hookSpecificOutput to
    disambiguate which event schema the additionalContext belongs to.
    """
    try:
        if not context:
            print("{}")
            return
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": event_name,
                        "additionalContext": context,
                    }
                }
            )
        )
    except Exception:
        print("{}")


def emit_text(text):
    try:
        print(text if text else "")
    except Exception:
        print("")


def _session_launch_dir(data):
    """Return the session's launch directory, using the shared resolver."""
    module = _workspace_resolver()
    if module is not None:
        return module.session_launch_dir(data.get("cwd"))
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    try:
        return Path(raw).resolve()
    except Exception:
        return None


def handle_session_start(data):
    try:
        manifest_path, project_root = find_manifest(data.get("cwd"))
        if not manifest_path:
            # No DevFlow state in this directory. Distinguish "never initialised"
            # (offer /devflow init) from "initialised but no active task yet"
            # (stay quiet). The session's launch directory is the authority.
            launch = _session_launch_dir(data)
            has_devflow = bool(launch and (launch / ".devflow").is_dir())
            if not has_devflow and check_rules_installed():
                return emit(
                    "[DevFlow] This directory is not initialised for DevFlow. "
                    "Run /devflow init to set it up (init will ask which workspace "
                    "to inherit rules/config from: itself, its parent, or a custom "
                    "path). Until then DevFlow stays inactive here.",
                    "SessionStart",
                )
            if not check_rules_installed():
                return emit(
                    "[DevFlow] Plugin installed but rules not yet set up. "
                    "Run /devflow init in a project to install rules and start.",
                    "SessionStart",
                )
            return emit("", "SessionStart")
        phase = read_state_phase(manifest_path)
        work_type = read_work_type(manifest_path)
        tasks = read_tasks_summary(manifest_path, phase)
        ctx = f"[DevFlow] Active project: {project_root.name} | type: {work_type} | phase: {phase}."
        if tasks:
            ctx += f" Tasks: {tasks}."
        ctx += " Gates wait for your approval; /devflow status for details."
        return emit(ctx, "SessionStart")
    except Exception:
        return emit("", "SessionStart")


# Natural-language entry (ADR-0006 D4): a keyword prefilter keeps the model
# judgement cheap. This hook runs on every prompt, so a full model call on
# chit-chat would be waste; the prefilter decides what even deserves a look.
_INTENT_KEYWORDS = (
    "开发",
    "实现",
    "功能",
    "需求",
    "重构",
    "优化",
    "修",
    "bug",
    "报错",
    "异常",
    "崩溃",
    "feature",
    "implement",
    "refactor",
    "fix",
)

_SLASH_COMMAND = re.compile(r"^\s*/\w")


def detect_intent_candidate(prompt):
    """Return ``True`` when *prompt* might be a development request.

    Deliberately coarse and local: no model call happens here. A hit only
    means "worth asking the model", and the confirmation step in the injected
    context is what protects against a wrong guess.
    """
    try:
        text = (prompt or "").strip()
        if not text or _SLASH_COMMAND.match(text):
            return False
        lowered = text.lower()
        return any(word in lowered for word in _INTENT_KEYWORDS)
    except Exception:
        return False


def handle_user_prompt(data):
    try:
        manifest_path, _ = find_manifest(data.get("cwd"))
        if not manifest_path:
            # No active DevFlow state: the natural-language entry is the one
            # thing worth doing here. Ask the model to judge, and gate entry
            # behind an explicit confirmation so a wrong guess costs one reply
            # rather than a whole workflow.
            prompt = data.get("prompt") or data.get("user_prompt") or ""
            if detect_intent_candidate(prompt):
                return emit(
                    "[DevFlow] This looks like a development request. Judge the intent: "
                    "new feature (start) or bug fix (fix). If it is one, confirm with the "
                    "user in one line before doing anything else — do not start the "
                    "workflow unprompted. If it is not, ignore this notice.",
                    "UserPromptSubmit",
                )
            return emit("", "UserPromptSubmit")
        phase = read_state_phase(manifest_path)
        # ``prd_review`` is retired (ADR-0006 D1); old task.yaml files still
        # carry it, so it maps onto the merged gate instead of dropping the
        # notice.
        if phase == "prd_review":
            phase = "plan_review"
        # v2 Gate/waiting statuses plus legacy manifest phases (old projects).
        gate_phases = {
            "qa",
            "prd_review",
            "plan_review",
            "deliver_confirm",
            "classify",
            "product_qa",
            "gate_prd",
            "gate_arch",
            "acceptance",
            "delivery",
        }
        if phase in gate_phases:
            # ``qa`` is the design-time recall point (SKILL: recall before
            # writing the plan). Left to the model's memory, it was skipped in
            # the 2026-11 dogfood — the hook has to say it, not hope for it.
            if phase == "qa":
                return emit(
                    "[DevFlow] qa phase: do the design-time recall now if you have not — "
                    "call memorant_recall with the core intent + domain words, and fill the "
                    "plan's 历史经验 section before drafting anything. "
                    "Plan approval and delivery are the only gates; work runs to the next one.",
                    "UserPromptSubmit",
                )
            return emit(
                f"[DevFlow] Awaiting your review/approval in {phase} phase.",
                "UserPromptSubmit",
            )
        return emit("", "UserPromptSubmit")
    except Exception:
        return emit("", "UserPromptSubmit")


def handle_pre_compact(data):
    try:
        manifest_path, project_root = find_manifest(data.get("cwd"))
        if not manifest_path:
            return emit_text("")
        phase = read_state_phase(manifest_path)
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        summary = (
            f"[DevFlow State - preserve through compaction]\n"
            f"Project: {project_root.name}\n"
            f"Phase: {phase}\n\n"
            f"Manifest:\n{content[:2000]}"
        )
        return emit_text(summary)
    except Exception:
        try:
            manifest_path, project_root = find_manifest(data.get("cwd"))
            phase = read_state_phase(manifest_path) if manifest_path else "unknown"
            return emit_text(f"[DevFlow] Phase: {phase}")
        except Exception:
            return emit_text("")


def main():
    try:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            data = {}

        event = data.get("hook_event_name", "") or ""

        handlers = {
            "SessionStart": handle_session_start,
            "UserPromptSubmit": handle_user_prompt,
            "PreCompact": handle_pre_compact,
        }

        handler = handlers.get(event)
        if handler:
            handler(data)
        else:
            print("{}")
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
