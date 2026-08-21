#!/usr/bin/env python3
"""DevFlow hook handler — processes Claude Code hook events.

Fail-open: any exception results in empty JSON output so the user
is never blocked.

For automatic phases, the Stop hook blocks the stop once and instructs the
main Agent to continue with ``/devflow next``. ``stop_hook_active`` disables
that block on the host's follow-up Stop event to prevent an infinite loop.
"""
import glob
import json
import sys
import os
from pathlib import Path


def find_plugin_root():
    """Locate the devflow plugin directory.

    Checks in order:
      1. CLAUDE_PLUGIN_ROOT environment variable
      2. ~/.claude/plugins/cache/*/devflow/*/
      3. ~/.claude/plugins/marketplaces/devflow-marketplace/
      4. ~/.claude/plugins/marketplaces/*/devflow/
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
        matches = glob.glob(pattern)
        if matches:
            for m in matches:
                if os.path.isdir(m):
                    return m
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
        matches = glob.glob(pattern)
        if matches:
            for m in matches:
                if os.path.isdir(m):
                    return m
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


def find_manifest():
    """Walk up from CWD to find DevFlow state, migrating legacy metadata."""
    try:
        cwd = Path.cwd()
        plugin_root = Path(__file__).resolve().parent.parent
        core_dir = plugin_root / "core"
        if str(core_dir) not in sys.path:
            sys.path.insert(0, str(core_dir))
        from orchestrator.migration import migrate_legacy_project
        for parent in [cwd] + list(cwd.parents):
            devflow = parent / '.devflow'
            if (devflow / 'manifest.yaml').is_file():
                migrate_legacy_project(parent)
                return devflow / 'manifest.yaml', parent
            if (devflow / 'project.yaml').is_file():
                return devflow / 'project.yaml', parent
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
        manifest_path, project_root = find_manifest()
        if not manifest_path:
            if not check_rules_installed():
                return emit(
                    '[DevFlow] Plugin installed but rules not yet set up. '
                    'Run /devflow init in a project to install rules and start.',
                    'SessionStart',
                )
            return emit('', 'SessionStart')
        phase = read_manifest_phase(manifest_path)
        work_type = read_manifest_field(manifest_path, 'work_type:') or '—'
        tasks = read_tasks_summary(manifest_path, phase)
        ctx = f"[DevFlow] Active project: {project_root.name} | type: {work_type} | phase: {phase}."
        if tasks:
            ctx += f" Tasks: {tasks}."
        ctx += " Run /devflow status for details, /devflow next to continue."
        return emit(ctx, 'SessionStart')
    except Exception:
        return emit('', 'SessionStart')


def handle_user_prompt(data):
    try:
        manifest_path, _ = find_manifest()
        if not manifest_path:
            return emit('', 'UserPromptSubmit')
        phase = read_manifest_phase(manifest_path)
        gate_phases = {'gate_prd', 'gate_arch', 'acceptance', 'gate_delivery'}
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
        manifest_path, _ = find_manifest()
        if not manifest_path:
            return emit('', 'Stop')
        phase = read_manifest_phase(manifest_path)
        auto_phases = {
            'prd_writing', 'architecture', 'development',
            'testing', 'delivery', 'distill',
        }
        if phase in auto_phases:
            if data.get('stop_hook_active'):
                return emit('', 'Stop')
            return emit_stop_block(
                f"[DevFlow] Automatic phase '{phase}' is not finished. "
                "Continue the workflow by running /devflow next."
            )
        return emit('', 'Stop')
    except Exception:
        return emit('', 'Stop')


def handle_pre_compact(data):
    try:
        manifest_path, project_root = find_manifest()
        if not manifest_path:
            return emit_text('')
        phase = read_manifest_phase(manifest_path)
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
            manifest_path, project_root = find_manifest()
            phase = read_manifest_phase(manifest_path) if manifest_path else 'unknown'
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
