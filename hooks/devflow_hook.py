#!/usr/bin/env python3
"""DevFlow hook handler — processes Claude Code hook events.

Fail-open: any exception results in empty JSON output so the user
is never blocked.

For automatic phases the Stop hook keeps blocking so the main Agent continues
with tools until the next Gate. ``delivery`` is the nested confirmation Gate
(commit + push + PR): Stop is allowed so the user can answer. ``stop_hook_active``
does not release an unfinished automatic phase.
"""
import glob
import json
import sys
import os
from pathlib import Path


def _version_key(path):
    """Parse a trailing ``1.2.3``-style directory name for newest-cache picks."""
    name = os.path.basename(str(path).rstrip(os.sep))
    parts = []
    for bit in name.split('.'):
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
        env_root = os.environ.get('CLAUDE_PLUGIN_ROOT')
        if env_root and os.path.isdir(env_root):
            return env_root
    except Exception:
        pass

    try:
        home = Path.home()
        pattern = str(home / '.claude' / 'plugins' / 'cache' / '*' / 'devflow' / '*')
        newest = _newest_dir(glob.glob(pattern))
        if newest:
            return newest
    except Exception:
        pass

    try:
        home = Path.home()
        mp_direct = home / '.claude' / 'plugins' / 'marketplaces' / 'devflow-marketplace'
        if mp_direct.is_dir():
            return str(mp_direct)
    except Exception:
        pass

    try:
        home = Path.home()
        pattern = str(home / '.claude' / 'plugins' / 'marketplaces' / '*' / 'devflow')
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
        rules_file = Path.home() / '.claude' / 'rules' / 'engineering.md'
        return rules_file.exists()
    except Exception:
        return False


def memorant_available():
    """Check if Memorant plugin is installed by reading installed_plugins.json.

    Supports both v1 (top-level plugin name keys) and v2 (plugins dict with
    "name@marketplace" keys) formats.
    """
    try:
        installed_file = Path.home() / '.claude' / 'plugins' / 'installed_plugins.json'
        if not installed_file.exists():
            return False
        content = installed_file.read_text(encoding='utf-8', errors='replace')
        data = json.loads(content)
        if not isinstance(data, dict):
            return False
        # v2 format: {"version": 2, "plugins": {"memorant@marketplace": [...]}}
        plugins = data.get('plugins')
        if isinstance(plugins, dict):
            return any(k.split('@', 1)[0] == 'memorant' for k in plugins.keys())
        # v1 format: {"memorant": [...], ...}
        return 'memorant' in data
    except Exception:
        return False


def find_manifest(cwd=None):
    """Walk up from *cwd* (or process CWD) to find DevFlow state. Read-only.

    Lookup order: ``task.yaml`` (per-task phase), ``project.yaml``, then
    legacy ``manifest.yaml``. Migration stays in ``/devflow init`` / ``next``.
    Prefer the hook payload ``cwd`` so a latercomer worktree is not missed
    when the hook process starts in the main workspace.
    """
    try:
        raw = cwd or str(Path.cwd())
        start = Path(raw)
        if not start.is_absolute():
            start = (Path.cwd() / start).resolve()
        else:
            start = start.resolve()
        for parent in [start] + list(start.parents):
            devflow = parent / '.devflow'
            if (devflow / 'task.yaml').is_file():
                return devflow / 'task.yaml', parent
            if (devflow / 'project.yaml').is_file():
                return devflow / 'project.yaml', parent
            if (devflow / 'manifest.yaml').is_file():
                return devflow / 'manifest.yaml', parent
    except Exception:
        pass
    return None, None


def read_manifest_phase(manifest_path):
    """Extract current_phase from manifest.yaml without requiring yaml module."""
    try:
        content = manifest_path.read_text(encoding='utf-8', errors='replace')
        for line in content.splitlines():
            line = line.strip()
            if line.startswith('current_phase:'):
                return line.split(':', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return 'unknown'


def read_task_phase(task_path):
    """Extract ``task.current_phase`` from a ``task.yaml`` state file.

    Unlike the legacy manifest, task.yaml nests ``current_phase`` under the
    ``task:`` section, so a naive top-level ``current_phase:`` scan misses it.
    """
    try:
        content = task_path.read_text(encoding='utf-8', errors='replace')
        in_task = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped == 'task:':
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(':'):
                break
            if in_task and stripped.startswith('current_phase:'):
                return stripped.split(':', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return 'unknown'


def read_state_phase(state_path):
    """Read the current phase from whichever state file *state_path* points at.

    ``task.yaml`` (isolated worktree) and ``manifest.yaml``/``project.yaml``
    (legacy) store the phase in different positions, so dispatch on filename.
    """
    name = state_path.name
    if name == 'task.yaml':
        return read_task_phase(state_path)
    return read_manifest_phase(state_path)


def read_work_type(state_path):
    """Read the work type (feature/bugfix/chore) from the state file.

    ``task.yaml`` stores it nested as ``task.kind``; the legacy manifest uses
    the top-level ``work_type:`` field. ``project.yaml`` carries no work type
    (it is project-level config), so it falls back to the neutral ``—``.
    """
    name = state_path.name
    if name == 'task.yaml':
        return read_task_kind(state_path) or '—'
    return read_manifest_field(state_path, 'work_type:') or '—'


def read_task_kind(task_path):
    """Extract ``task.kind`` from a ``task.yaml`` state file.

    Mirrors :func:`read_task_phase` — ``kind`` nests under the ``task:``
    section, so a top-level scan would miss it.
    """
    try:
        content = task_path.read_text(encoding='utf-8', errors='replace')
        in_task = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped == 'task:':
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(':'):
                break
            if in_task and stripped.startswith('kind:'):
                return stripped.split(':', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return None


def read_manifest_field(manifest_path, field):
    """Extract a top-level or project-level string field from manifest.yaml."""
    try:
        content = manifest_path.read_text(encoding='utf-8', errors='replace')
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(field + ':'):
                return stripped.split(':', 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return None


def read_tasks_summary(manifest_path, phase):
    """Count completed/total tasks for development phase.

    Parses the tasks list in the manifest, counting items by status field.
    Returns '3/5 tasks' or empty string.
    """
    try:
        content = manifest_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines()
        in_tasks = False
        tasks_indent = None
        completed = 0
        total = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('tasks:'):
                in_tasks = True
                tasks_indent = len(line) - len(line.lstrip())
                continue
            if in_tasks:
                current_indent = len(line) - len(line.lstrip())
                if stripped and current_indent <= tasks_indent and not stripped.startswith('-'):
                    break
                if stripped.startswith('- id:'):
                    total += 1
                if stripped.startswith('status: completed') or stripped.endswith('status: completed'):
                    completed += 1
        if total > 0:
            return f"{completed}/{total} tasks"
    except Exception:
        pass
    return ''


def emit(context, event_name='Stop'):
    """Emit JSON hook output.

    Claude Code requires hookEventName inside hookSpecificOutput to
    disambiguate which event schema the additionalContext belongs to.
    """
    try:
        if not context:
            print('{}')
            return
        print(json.dumps({
            'hookSpecificOutput': {
                'hookEventName': event_name,
                'additionalContext': context,
            }
        }))
    except Exception:
        print('{}')


def emit_stop_block(reason):
    """Prevent Stop so the main Agent can continue an automatic phase."""
    try:
        print(json.dumps({"decision": "block", "reason": reason}))
    except Exception:
        print("{}")


def emit_text(text):
    try:
        print(text if text else '')
    except Exception:
        print('')


def handle_session_start(data):
    try:
        manifest_path, project_root = find_manifest(data.get('cwd'))
        if not manifest_path:
            if not check_rules_installed():
                return emit(
                    '[DevFlow] Plugin installed but rules not yet set up. '
                    'Run /devflow init in a project to install rules and start.',
                    'SessionStart',
                )
            return emit('', 'SessionStart')
        phase = read_state_phase(manifest_path)
        work_type = read_work_type(manifest_path)
        tasks = read_tasks_summary(manifest_path, phase)
        ctx = f"[DevFlow] Active project: {project_root.name} | type: {work_type} | phase: {phase}."
        if tasks:
            ctx += f" Tasks: {tasks}."
        ctx += " Automatic phases continue to the next Gate; /devflow status for details."
        return emit(ctx, 'SessionStart')
    except Exception:
        return emit('', 'SessionStart')


def handle_user_prompt(data):
    try:
        manifest_path, _ = find_manifest(data.get('cwd'))
        if not manifest_path:
            return emit('', 'UserPromptSubmit')
        phase = read_state_phase(manifest_path)
        gate_phases = {
            'classify', 'product_qa', 'gate_prd', 'gate_arch',
            'acceptance', 'delivery',
        }
        if phase in gate_phases:
            return emit(
                f"[DevFlow] Awaiting your review/approval in {phase} phase.",
                'UserPromptSubmit',
            )
        return emit('', 'UserPromptSubmit')
    except Exception:
        return emit('', 'UserPromptSubmit')


def handle_stop(data):
    try:
        manifest_path, _ = find_manifest(data.get('cwd'))
        if not manifest_path:
            return emit('', 'Stop')
        phase = read_state_phase(manifest_path)
        auto_phases = {
            'prd_writing', 'architecture', 'development',
            'testing', 'distill',
        }
        if phase in auto_phases:
            return emit_stop_block(
                f"[DevFlow] Automatic phase '{phase}' is not finished. "
                "Do not stop and do not wait for /devflow next. "
                "Continue with tools until the next Gate "
                "(gate_prd, gate_arch, acceptance, or delivery confirmation)."
            )
        return emit('', 'Stop')
    except Exception:
        return emit('', 'Stop')


def handle_pre_compact(data):
    try:
        manifest_path, project_root = find_manifest(data.get('cwd'))
        if not manifest_path:
            return emit_text('')
        phase = read_state_phase(manifest_path)
        content = manifest_path.read_text(encoding='utf-8', errors='replace')
        summary = (
            f"[DevFlow State - preserve through compaction]\n"
            f"Project: {project_root.name}\n"
            f"Phase: {phase}\n\n"
            f"Manifest:\n{content[:2000]}"
        )
        return emit_text(summary)
    except Exception:
        try:
            manifest_path, project_root = find_manifest(data.get('cwd'))
            phase = read_state_phase(manifest_path) if manifest_path else 'unknown'
            return emit_text(f"[DevFlow] Phase: {phase}")
        except Exception:
            return emit_text('')


def main():
    try:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            data = {}

        event = data.get('hook_event_name', '') or ''

        handlers = {
            'SessionStart': handle_session_start,
            'UserPromptSubmit': handle_user_prompt,
            'Stop': handle_stop,
            'PreCompact': handle_pre_compact,
        }

        handler = handlers.get(event)
        if handler:
            handler(data)
        else:
            print('{}')
    except Exception:
        print('{}')


if __name__ == '__main__':
    main()
