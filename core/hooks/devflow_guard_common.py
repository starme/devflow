#!/usr/bin/env python3
"""Shared utilities for DevFlow guard hooks (redline-guard, audit-log).

No third-party dependencies. All functions fail-safe: they return empty
defaults rather than raising, so hooks never block the user on internal errors.
"""

import os
import re
import sys
from pathlib import Path

# ``core/workspace.py`` is the single authority for project-root discovery.
# Load it by file location so the guard works both from the plugin checkout and
# from an installed cache path, where ``core`` is not an importable package.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from workspace import (  # noqa: E402
        resolve_project_root,
        resolve_session_project_root,
    )
except ImportError:  # pragma: no cover - defensive: fall back to local search
    resolve_project_root = None
    resolve_session_project_root = None

# ---------------------------------------------------------------------------
# Project root / context discovery
# ---------------------------------------------------------------------------


def find_project_root(payload_cwd=None):
    """Return the session's authoritative project root, or ``None``.

    The hook stdin ``cwd`` follows the agent: it changes after a ``cd`` or after
    entering a worktree.  The project root must not drift that way, so the
    fixed ``CLAUDE_PROJECT_DIR`` is tried first (see
    ``core/workspace.resolve_session_project_root``), with the payload ``cwd``
    only as a fallback for hosts that do not set it.  A candidate is a root only
    when it owns ``.devflow/`` itself; no ancestor is ever consulted.
    """
    if resolve_session_project_root is not None:
        try:
            return resolve_session_project_root(payload_cwd)
        except Exception:
            return None
    try:
        raw = os.environ.get("CLAUDE_PROJECT_DIR") or payload_cwd or os.getcwd()
        start = Path(raw).resolve()
        return start if (start / ".devflow").is_dir() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Worktree detection
# ---------------------------------------------------------------------------


def detect_worktree(cwd):
    """Detect a Claude subagent or DevFlow task worktree.

    Returns ``(worktree_root, main_root)`` or ``(None, None)``. DevFlow task
    worktrees live outside the repository and are identified by ``task.yaml``;
    Claude Task worktrees retain the existing ``.claude/worktrees/agent-*``
    convention.
    """
    try:
        p = Path(cwd).resolve()
        for parent in [p, *list(p.parents)]:
            if (parent / ".devflow" / "task.yaml").is_file():
                project_root = parent
                while (
                    project_root.parent != project_root
                    and project_root.name != ".devflow-worktrees"
                ):
                    project_root = project_root.parent
                if project_root.name == ".devflow-worktrees":
                    # Layout: <repo.parent>/.devflow-worktrees/<repo.name>/<task-id>
                    # main_root must be the git repo, not the directory that
                    # contains `.devflow-worktrees`.
                    repo_name = parent.parent.name
                    repo_root = project_root.parent / repo_name
                    return parent, repo_root
        parts = p.parts
        for i in range(len(parts) - 1):
            if (
                parts[i] == ".claude"
                and i + 1 < len(parts)
                and parts[i + 1] == "worktrees"
                and i + 2 < len(parts)
                and parts[i + 2].startswith("agent-")
            ):
                wt_root = Path(*parts[: i + 3])
                main_root = Path(*parts[:i])
                return wt_root, main_root
    except Exception:
        pass
    return None, None


def map_worktree_path(abs_path, wt_root, main_root):
    """Map an absolute path inside a worktree to its main-workspace equivalent.

    E.g. ``/proj/.claude/worktrees/agent-x/server/foo.go``
      → ``/proj/server/foo.go``
    """
    try:
        rel = Path(abs_path).resolve().relative_to(wt_root.resolve())
        return str((main_root / rel).resolve())
    except (ValueError, Exception):
        return str(abs_path)


def _plugin_version_key(path):
    """Parse a trailing ``1.2.3``-style directory name for newest-cache picks."""
    name = os.path.basename(str(path).rstrip(os.sep))
    parts = []
    for bit in name.split("."):
        if bit.isdigit():
            parts.append(int(bit))
        else:
            return (0,)
    return tuple(parts) if parts else (0,)


def _newest_plugin_dir(paths):
    """Pick the newest existing directory: version name first, then mtime."""
    dirs = [p for p in paths if os.path.isdir(p)]
    if not dirs:
        return None
    return max(dirs, key=lambda p: (_plugin_version_key(p), os.path.getmtime(p)))


def _find_core_dir():
    """Locate the platform-agnostic ``core/`` directory (bundled resources).

    The core directory holds ``templates/`` and ``rules/``. It is resolved
    independently of any host platform so the same scripts work under
    Claude Code, Codex, Cursor, or a plain shell.
    """
    # 1. Walk up from this script: core/hooks/.. = core/
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent
    if (candidate / "templates" / "redlines.yaml").is_file():
        return candidate

    # 2. Claude Code: CLAUDE_PLUGIN_ROOT points at the plugin root; core/ is inside.
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        core = Path(env_root) / "core"
        if (core / "templates" / "redlines.yaml").is_file():
            return core

    # 3. Claude Code cache fallback — newest version/mtime, not first glob hit.
    try:
        home = Path.home()
        candidates = []
        for p in (home / ".claude" / "plugins" / "cache").glob("*/devflow/*"):
            core = p / "core"
            if (core / "templates" / "redlines.yaml").is_file():
                candidates.append(str(p))
        if candidates:
            newest = _newest_plugin_dir(candidates)
            if newest:
                return Path(newest) / "core"
    except Exception:
        pass

    return None


def _parse_workspace_yaml(project_root, filename):
    """Parse workspace paths from a DevFlow YAML file.

    Returns a dict with ``root``, ``backend``, ``frontend`` keys.
    This is a *minimal* YAML reader — it only extracts the fields the
    guard hooks need, without requiring PyYAML.
    """
    ws = {"root": str(project_root), "backend": "", "frontend": ""}
    try:
        manifest = project_root / ".devflow" / filename
        if not manifest.is_file():
            return ws

        content = manifest.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        in_workspace = False
        current_subkey = None

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip())

            # Top-level workspace: section
            if indent == 0 and stripped == "workspace:":
                in_workspace = True
                current_subkey = None
                continue

            if in_workspace:
                # Left workspace section when we hit another top-level key
                if indent == 0 and stripped.endswith(":"):
                    break

                # Direct children of workspace (root:, backend:, frontend:)
                if indent == 2 and ":" in stripped and not stripped.startswith("-"):
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == "root":
                        ws["root"] = val or str(project_root)
                        current_subkey = None
                    elif key in ("backend", "frontend"):
                        current_subkey = key
                        # If value is on same line (not a nested map)
                        if val and val != "":
                            ws[key] = val
                            current_subkey = None
                    else:
                        current_subkey = None
                    continue

                # Nested path: under backend:/frontend:
                if current_subkey and indent >= 4 and ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == "path" and val:
                        ws[current_subkey] = val
                        current_subkey = None

        # Normalise null → empty string
        for k in ("backend", "frontend"):
            if ws[k] in ("null", "~", "none"):
                ws[k] = ""

    except Exception:
        pass

    return ws


def _parse_manifest_workspace(project_root):
    """Workspace from ``project.yaml``, then legacy ``manifest.yaml``."""
    ws = _parse_workspace_yaml(project_root, "project.yaml")
    if ws.get("backend") or ws.get("frontend"):
        return ws
    legacy = _parse_workspace_yaml(project_root, "manifest.yaml")
    if legacy.get("backend") or legacy.get("frontend"):
        return legacy
    if (project_root / ".devflow" / "project.yaml").is_file():
        return ws
    return legacy


def _parse_workspaces(project_root):
    """Parse the multi-repo ``workspaces:`` list from ``project.yaml``.

    Returns a list of ``{"track": ..., "git_root": ...}`` dicts (absolute
    git_root).  An absent or single-repo project yields ``[]``.  This is the
    multi-repo counterpart of ``_parse_workspace_yaml``: each endpoint maps a
    track to an independent git repository rather than a subdirectory of the
    anchor root.

    Relative ``git_root`` values resolve against *project_root* — the directory
    that owns the ``.devflow/`` being read. ``path:`` is an alias of
    ``git_root:``; git_root wins when both appear. Only a first-key
    ``- track:`` item names an endpoint; residue items and legacy shapes whose
    track would only come from an indented line are skipped.

    Multi-repo capability belongs to the directory that *declares* the list.
    Callers pass the root the session actually started in, so a child
    repository's own ``project.yaml`` is read as its own project: if it
    declares ``workspaces:`` those endpoints are the child's, not an ancestor's,
    and cross-repo behaviour is a property of where the session runs, not of an
    upward search.

    Raises: never. This is a zero-dependency fail-safe hook: an endpoint with a
    track but no root key is skipped here, not rejected. The orchestrator's
    ``_resolve_endpoints`` raises loudly at task creation for first-key named
    endpoints — the disambiguation belongs there, not in a hook that gates
    every tool call.
    """
    manifest = project_root / ".devflow" / "project.yaml"
    if not manifest.is_file():
        return []
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    def scalar(val):
        # Keep in sync with worktree_manager._scalar: strip trailing comments
        # before quotes so ``path: ./fe # alias`` stays a usable path.
        if "#" in val:
            val = val.split("#", 1)[0]
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        return val.strip()

    endpoints = []
    in_workspaces = False
    current = None
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and stripped == "workspaces:":
            in_workspaces = True
            current = None
            continue
        if in_workspaces:
            if indent == 0 and stripped.endswith(":"):
                break
            if indent == 2 and stripped.startswith("- "):
                if current and current.get("track") and (current.get("git_root") or current.get("path")):
                    endpoints.append(current)
                # Only a first-key ``- track:`` item names an endpoint. Other
                # first keys are residue or a legacy shape main never parsed.
                first_key, _, first_val = stripped[2:].partition(":")
                if first_key.strip() == "track":
                    current = {"track": scalar(first_val)}
                else:
                    current = {}
                    val = scalar(first_val)
                    if first_key.strip() in ("git_root", "path") and val:
                        current[first_key.strip()] = val
                continue
            if indent >= 4 and ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = scalar(val)
                # Indented track: is deliberately NOT recorded (H1 parity).
                if key in ("git_root", "path") and val:
                    current[key] = val
    if current and current.get("track") and (current.get("git_root") or current.get("path")):
        endpoints.append(current)

    resolved = []
    for ep in endpoints:
        # ``path:`` is an alias of ``git_root:``; git_root wins when both appear.
        # A named endpoint missing both keys is skipped here (fail-safe hook —
        # never raise); the orchestrator's _resolve_endpoints raises loudly at
        # task creation so the misconfiguration cannot pass silently.
        raw_root = ep.get("git_root") or ep.get("path")
        git_root = Path(raw_root)
        if not git_root.is_absolute():
            git_root = (project_root / git_root).resolve()
        else:
            git_root = git_root.resolve()
        resolved.append({"track": ep["track"], "git_root": str(git_root)})
    return resolved


def _parse_task_phase(project_root):
    """Read ``task.current_phase`` from ``task.yaml`` if present."""
    try:
        task_path = project_root / ".devflow" / "task.yaml"
        if not task_path.is_file():
            return ""
        content = task_path.read_text(encoding="utf-8", errors="replace")
        in_task = False
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip())
            if indent == 0 and stripped == "task:":
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(":"):
                break
            if in_task and stripped.startswith("current_phase:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _parse_task_id(project_root):
    """Read ``task.id`` from ``task.yaml`` if present.

    Mirrors :func:`_parse_task_phase` — the id nests under the ``task:``
    section, so a top-level scan would miss it.  Returns ``""`` when the
    task.yaml is absent or malformed.
    """
    try:
        task_path = project_root / ".devflow" / "task.yaml"
        if not task_path.is_file():
            return ""
        content = task_path.read_text(encoding="utf-8", errors="replace")
        in_task = False
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip())
            if indent == 0 and stripped == "task:":
                in_task = True
                continue
            if in_task and indent == 0 and stripped.endswith(":"):
                break
            if in_task and stripped.startswith("id:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def archived_index_path(project_root):
    """Return the archive index path for the current task, or ``None``.

    ``artifact_publish.publish`` writes ``<project_root>/.devflow/tasks/<task-id>/README.md``
    as the terminal step of a successful publish, so the index file is the
    lightweight "archived" signal the delivery guard uses — no content hashing.
    Returns ``None`` when the task id cannot be read (legacy manifest or missing
    task.yaml).
    """
    task_id = _parse_task_id(project_root)
    if not task_id:
        return None
    return project_root / ".devflow" / "tasks" / task_id / "README.md"


def task_needs_archive(project_root):
    """Return ``True`` when the current task has process artifacts that must
    still be published before delivery can commit.

    True only for formal tasks (a ``task.yaml`` with a readable id) whose archive
    index ``.devflow/tasks/<task-id>/README.md`` does not yet exist.  Legacy
    manifest projects (no task.yaml) have no formal-task archive, so they return
    ``False`` and are never blocked — the archive gate applies only to the
    isolated-task workflow that ``artifact_publish`` targets.
    """
    index = archived_index_path(project_root)
    if index is None:
        return False
    return not index.is_file()


def _parse_manifest_phase(project_root):
    """Read ``project.current_phase`` from manifest.yaml."""
    try:
        manifest = project_root / ".devflow" / "manifest.yaml"
        if not manifest.is_file():
            return ""
        content = manifest.read_text(encoding="utf-8", errors="replace")
        in_project = False
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip())
            if indent == 0 and stripped == "project:":
                in_project = True
                continue
            if in_project and indent == 0 and stripped.endswith(":"):
                break
            if in_project and stripped.startswith("current_phase:"):
                val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                return val
    except Exception:
        pass
    return ""


def load_context(project_root):
    """Build the runtime context for guard hooks.

    v2 (ADR-0005): the runtime ``context.json`` is retired. ``task.yaml`` is
    the single source of run state — ``task.id`` plays the role the old
    ``run_id`` did, and the phase comes from ``task.yaml`` (legacy
    ``manifest.yaml`` remains a read-only fallback).

    Sources, in order:

    1. ``.devflow/task.yaml`` — active task (``run_id`` = ``task.id``,
       ``current_phase``).
    2. ``.devflow/project.yaml`` — workspace root/backend/frontend paths,
       with a legacy ``manifest.yaml`` fallback.

    Always returns at least ``{"workspace": {...}}`` so boundary checks
    can function.
    """
    ctx = {}

    run_id = _parse_task_id(project_root)
    if run_id:
        ctx["run_id"] = run_id

    manifest_ws = _parse_manifest_workspace(project_root)
    ctx["workspace"] = dict(manifest_ws)

    # 2b. Attach multi-repo endpoints (if declared) for track boundary checks.
    # ``endpoints`` is only set when a ``workspaces:`` list exists; absent on
    # single-repo projects so boundary checks keep using backend/frontend dirs.
    endpoints = _parse_workspaces(project_root)
    ctx["workspace"]["endpoints"] = endpoints

    # 3. Phase: task.yaml, then legacy manifest fallback
    phase = _parse_task_phase(project_root) or _parse_manifest_phase(project_root)
    if phase:
        ctx["current_phase"] = phase

    return ctx


_EMPTY_REDLINES = {
    "forbidden": [],
    "forbidden_negations": [],
    "protected": [],
    "protected_negations": [],
    "config_protected": [],
    "config_protected_negations": [],
    "approval_required": [],
    "approval_required_negations": [],
}


def _parse_redlines_file(rl_file):
    """Parse a redlines.yaml file into the structured dict."""
    result = {k: list(v) for k, v in _EMPTY_REDLINES.items()}
    section = None
    for raw_line in rl_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        # Section header (ends with ':')
        if not line.startswith(" ") and not line.startswith("-") and stripped.endswith(":"):
            key = stripped[:-1].strip()
            section = key if key in result else None
            continue

        # List item
        if section and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if not value:
                continue
            if value.startswith("!"):
                result[section + "_negations"].append(value[1:])
            else:
                result[section].append(value)
    return result


def load_redlines(project_root):
    """Load redline rules.

    Lookup order:
      1. ``.devflow/redlines.yaml`` — project-level custom rules (created by
         ``/devflow init`` from the template, then editable by the user).
      2. ``<plugin>/templates/redlines.yaml`` — built-in defaults, used as a
         safety net when the project file is absent.

    Returns a dict with ``forbidden``, ``protected``, ``approval_required``
    lists and their parallel ``*_negations`` lists.
    """
    # 1. Project-level
    try:
        rl_file = project_root / ".devflow" / "redlines.yaml"
        if rl_file.is_file():
            return _parse_redlines_file(rl_file)
    except Exception:
        pass

    # 2. Bundled default fallback (core/templates/redlines.yaml)
    try:
        core_dir = _find_core_dir()
        if core_dir:
            default_file = core_dir / "templates" / "redlines.yaml"
            if default_file.is_file():
                return _parse_redlines_file(default_file)
    except Exception:
        pass

    return {k: list(v) for k, v in _EMPTY_REDLINES.items()}


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------

_GLOB_CACHE = {}


def _glob_to_regex(pattern):
    """Convert a glob pattern to a compiled regex.

    Supports:
      - ``**``  → matches any characters including ``/``
      - ``*``   → matches any characters except ``/``
      - ``?``   → matches any single character except ``/``
      - ``[..]`` → character class (passed through)
      - Everything else is regex-escaped.
    """
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]

    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                tokens.append(".*")
                i += 2
                # Consume a trailing slash after ** so "**/foo" matches "foo"
                if i < n and pattern[i] == "/":
                    i += 1
                continue
            else:
                tokens.append("[^/]*")
        elif c == "?":
            tokens.append("[^/]")
        elif c == "[":
            # Character class - find closing ]
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                tokens.append(re.escape("["))
            else:
                cls = pattern[i + 1 : j]
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                tokens.append("[" + cls + "]")
                i = j
        elif c in (".", "^", "$", "+", "{", "}", "(", ")", "|", "\\"):
            tokens.append(re.escape(c))
        else:
            tokens.append(c)
        i += 1

    regex = re.compile("^" + "".join(tokens) + "$")
    _GLOB_CACHE[pattern] = regex
    return regex


def path_matches_glob(rel_path, pattern):
    """Check whether *rel_path* (forward-slash, relative to project root)
    matches *pattern*.

    The pattern is tested against both the full relative path and the
    basename so that patterns like ``*.pem`` match regardless of directory.
    """
    regex = _glob_to_regex(pattern)
    if regex.match(rel_path):
        return True
    basename = rel_path.rsplit("/", 1)[-1]
    return bool(regex.match(basename))


def path_in_redline_category(rel_path, patterns, negations):
    """Return ``True`` if *rel_path* matches any positive pattern and does
    not match any negation pattern."""
    matched = False
    for p in patterns:
        if path_matches_glob(rel_path, p):
            matched = True
            break
    if not matched:
        return False
    return all(not path_matches_glob(rel_path, neg) for neg in negations)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Files under .devflow/ that agents are allowed to write *even when outside
# their track boundary*.  This covers process artifacts (reports, scope, runs)
# that any agent may need to produce.  Contracts are intentionally excluded —
# only the architect (who has no track boundary) writes them.
_DEVFLOW_ARTIFACT_PREFIXES = (
    ".devflow/runs/",
    ".devflow/sessions/",
    ".devflow/tasks/",
)
_DEVFLOW_ARTIFACT_FILES = frozenset(
    {
        ".devflow/scope.yaml",
        ".devflow/diagnosis.md",
        ".devflow/architecture.md",
        # The two entries below are guard-only: agents may write them, but the
        # delivery flow never collects them into a commit (they document design
        # intent rather than task artifacts). This set is a superset of
        # ``delivery.DELIVERY_ARTIFACT_FILES`` — see test_delivery.py.
        ".devflow/frontend-components.md",
        ".devflow/impact-analysis.md",
        ".devflow/prd.md",
        ".devflow/card.md",
        ".devflow/plan.md",
        ".devflow/review-report.md",
        ".devflow/verification-report.md",
        ".devflow/memorant-journal-investigation.md",
        ".devflow/backend-task-report.md",
        ".devflow/frontend-task-report.md",
        ".devflow/test-report.md",
        ".devflow/task-report.md",
        ".devflow/acceptance-scenarios.md",
        ".devflow/acceptance-report.md",
        ".devflow/pr.md",
        ".devflow/delivery.yaml",
        ".devflow/retrospective.md",
    }
)

# Published task artifacts now live under ``.devflow/tasks/<task-id>/``, which
# is already covered by ``_DEVFLOW_ARTIFACT_PREFIXES`` above.  The former
# ``docs/tasks/`` track is retired, so there is no separate published-prefix
# whitelist — the single ``.devflow/`` channel is the sole authority (ADR-002
# single-main-channel principle).  Sensitive-file protection is untouched:
# forbidden files (``.env``/``.pem``/``secrets.*``) are still denied by the
# redline checks that run *before* the boundary check in ``redline-guard.py``.


def is_devflow_artifact(rel_path):
    """Return ``True`` if *rel_path* is a ``.devflow/`` artifact that agents
    are permitted to write.

    Protected configuration files (rules/, redlines.yaml, manifest.yaml,
    context.json) are NOT considered artifacts and remain boundary-protected.
    """
    if rel_path.startswith(".devflow/"):
        if rel_path in _DEVFLOW_ARTIFACT_FILES:
            return True
        return any(rel_path.startswith(prefix) for prefix in _DEVFLOW_ARTIFACT_PREFIXES)
    return False


# Configuration files ``/devflow init`` is allowed to create while a project is
# being initialised. The init command's whole job is to write these from the
# bundled templates, so blocking them makes init impossible. This list is only
# honoured while the init window is open (see :func:`is_init_window_open`); in
# the task phase these same paths stay DevFlow-protected.
_INIT_CONFIG_FILES = frozenset(
    {
        ".devflow/project.yaml",
        ".devflow/redlines.yaml",
        ".devflow/manifest.yaml",
    }
)
_INIT_CONFIG_PREFIXES = (
    ".devflow/rules/",
    ".devflow/contracts/",
)


def is_init_window_open(project_root):
    """Return ``True`` while *project_root* has not been initialised yet.

    The window is open only when the project carries no DevFlow state at all:
    no ``task.yaml`` (never started a task), no ``project.yaml`` and no legacy
    ``manifest.yaml`` (never written project config). In that state
    ``/devflow init`` legitimately creates the config from templates. The
    moment any of those exist the project counts as initialised, the window
    closes, and the DevFlow-protected rule applies in full — so an already
    configured project cannot use "no task yet" to rewrite its own config.

    Fail-closed: any error reading the state counts as "window closed", so a
    guard bug can never open the window by accident.
    """
    try:
        devflow = Path(project_root).resolve() / ".devflow"
        for name in ("task.yaml", "project.yaml", "manifest.yaml"):
            if (devflow / name).is_file():
                return False
        return True
    except Exception:
        return False


def is_devflow_init_path(rel_path):
    """Return ``True`` for the config paths init is allowed to create."""
    if rel_path in _INIT_CONFIG_FILES:
        return True
    return any(rel_path.startswith(prefix) for prefix in _INIT_CONFIG_PREFIXES)


def is_devflow_protected(rel_path, init_window_open=False):
    """Return ``True`` when *rel_path* is DevFlow's own machinery, not an agent
    artifact — anything under ``.devflow/`` that is not a permitted artifact.

    Agents must not rewrite the rules that constrain them (``redlines.yaml``),
    the state that tracks them (``task.yaml``), the project config
    (``project.yaml``), the rule set (``rules/``) or the contracts.  With the
    per-track boundary retired, this is the dedicated guard for that area: the
    boundary rule now allows everything inside the project root, so without
    this check an agent could edit its own redlines or state.

    While *init_window_open* is true (no task yet), the init config paths are
    exempt — ``/devflow init`` writes exactly those from templates. Every other
    ``.devflow/`` path stays protected even then, so init cannot be used to
    scribble arbitrary files into DevFlow's machinery.
    """
    if not rel_path.startswith(".devflow/") or is_devflow_artifact(rel_path):
        return False
    return not (init_window_open and is_devflow_init_path(rel_path))


def to_rel_path(file_path, project_root):
    """Resolve *file_path* against the project root and return a forward-slash
    relative path string."""
    try:
        fp = Path(file_path)
        fp = (project_root / fp).resolve() if not fp.is_absolute() else fp.resolve()
        rel = fp.relative_to(project_root.resolve())
        return str(rel).replace(os.sep, "/")
    except Exception:
        # Path is outside project root - return absolute as-is
        return str(file_path).replace(os.sep, "/")


def get_target_paths(tool_name, tool_input, project_root, cwd=None):
    """Extract one or more file paths from a tool call.

    For Write/Edit/MultiEdit returns the single ``file_path``.
    For Bash, scans the command for redirection/tee/sed targets and returns
    any that resolve inside the project.

    Relative paths are resolved against *cwd* (the actual working directory
    of the tool call, which may be an isolated worktree), not against
    *project_root*.  This is critical when subagents run in worktrees: the
    hook must check the path the platform will actually write to.

    Returns a list of ``(rel_path, absolute_path)`` tuples where *rel_path*
    is relative to the logical project root (worktree prefix stripped) so
    that red-line patterns match correctly.
    """
    paths = []
    wt_root, main_root = detect_worktree(cwd) if cwd else (None, None)
    try:
        if tool_name in ("Read", "Write", "Edit", "MultiEdit"):
            fp = tool_input.get("file_path", "")
            if fp:
                abs_fp = Path(fp)
                if not abs_fp.is_absolute():
                    base = Path(cwd).resolve() if cwd else project_root
                    abs_fp = (base / fp).resolve()
                else:
                    abs_fp = abs_fp.resolve()
                rel = _compute_rel_path(str(abs_fp), project_root, wt_root, main_root)
                paths.append((rel, str(abs_fp)))
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            for rel, abs_fp in _extract_shell_write_targets(
                cmd, project_root, cwd, wt_root, main_root
            ):
                paths.append((rel, abs_fp))
    except Exception:
        pass
    return paths


def _compute_rel_path(abs_path, project_root, wt_root=None, main_root=None):
    """Compute a rel_path suitable for red-line pattern matching.

    In worktree mode, the absolute path is mapped to its main-workspace
    equivalent before computing the relative path, so that
    ``.../agent-xxx/server/foo.go`` becomes ``server/foo.go`` (matching
    patterns) rather than ``.claude/worktrees/agent-xxx/server/foo.go``.
    """
    try:
        if wt_root and main_root:
            mapped = map_worktree_path(abs_path, wt_root, main_root)
            return to_rel_path(mapped, main_root)
        return to_rel_path(abs_path, project_root)
    except Exception:
        return str(abs_path).replace(os.sep, "/")


# Patterns to detect shell-based file writes.
_SHELL_REDIRECT = re.compile(r"(?:&?)>>?\s*(?P<path>[^\s;|&<>]+)")
_SHELL_TEE = re.compile(r"\btee\s+(?:-[a-zA-Z]+\s+)*(?P<path>[^\s;|&<>]+)")
_SHELL_SED_I = re.compile(
    r"\bsed\s+-i\b(?:\s+''|\"\"|\s+'[^']*'|\s+\"[^\"]*\")?\s+"
    r"(?:-[eE]\s+[^']+?\s+)*(?P<path>[^\s;|&<>]+)"
)
_SHELL_CP_MV = re.compile(
    r"\b(?:cp|mv|install)\s+(?:-[a-zA-Z]+\s+)*"
    r"(?:[^\s;|&<>]+\s+)+(?P<path>[^\s;|&<>]+)"
)
_SHELL_PYTHON_C = re.compile(r"\bpython3?(?:\s+-(?!c\b)[^\s]+)*\s+-c\b")
_SHELL_SINGLE = re.compile(r"'([^']+)'")
_SHELL_DOUBLE = re.compile(r'"([^"]+)"')
_SHELL_PATCH_CMD = re.compile(r"\b(?:git\s+(?:apply|am)|patch)\b")
_SHELL_PATCH_FILE = re.compile(r"(?:^|[\s;|&])(?P<path>[^\s;|&<>]+\.(?:diff|patch))\b")
_PATCH_PLUSPLUS = re.compile(r"^\+\+\+ (?:[ab]/)?(?P<path>.+)$", re.M)


def _looks_like_path(value):
    """True when a quoted string is likely a filesystem path, not prose."""
    if not value or len(value) > 512 or value.startswith("/dev/"):
        return False
    if "/" in value or value.startswith("."):
        return True
    return bool(re.search(r"\.[A-Za-z0-9]{1,8}$", value))


def _paths_from_patch_file(raw, base):
    """Read ``+++`` targets from a .diff/.patch argument when the file exists."""
    try:
        patch = Path(raw)
        patch = (base / raw).resolve() if not patch.is_absolute() else patch.resolve()
        if not patch.is_file():
            return
        text = patch.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    for m in _PATCH_PLUSPLUS.finditer(text):
        dest = m.group("path").strip()
        if dest and dest != "/dev/null":
            yield dest


def _extract_shell_read_targets(command, project_root, cwd=None, wt_root=None, main_root=None):
    """Best-effort extraction of file paths a Bash command reads from.

    Only needed for the ``config_protected`` rule: writing is already covered
    by :func:`_extract_shell_write_targets`, but ``cat config/app.yaml`` reads
    with no redirection and would otherwise pass straight through the
    boundary. Deliberately narrow — it collects bare path arguments of common
    readers rather than parsing arbitrary shell syntax.
    """
    candidates = set()
    for segment in _split_shell_segments(command):
        parts = segment.split()
        if not parts:
            continue
        head = Path(parts[0]).name
        # ``cat file`` / ``head -n 5 file`` / ``grep pattern file``
        if head in _SHELL_READERS:
            for token in parts[1:]:
                if token.startswith("-") or not token:
                    continue
                if _looks_like_path(token):
                    candidates.add(token.strip("'\""))

    base = Path(cwd).resolve() if cwd else project_root
    results = []
    for raw in candidates:
        try:
            p = Path(raw)
            p = (base / raw).resolve() if not p.is_absolute() else p.resolve()
            rel = _compute_rel_path(str(p), project_root, wt_root, main_root)
            results.append((rel, str(p)))
        except Exception:
            continue
    return results


_SHELL_READERS = frozenset(
    {
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "grep",
        "egrep",
        "rg",
        "awk",
        "sed",
        "cut",
        "sort",
        "uniq",
        "diff",
        "jq",
        "yq",
    }
)


def _extract_shell_write_targets(command, project_root, cwd=None, wt_root=None, main_root=None):
    """Best-effort extraction of file paths that a Bash command writes to.

    Yields ``(rel_path, abs_path)`` tuples for targets inside the project.
    This is intentionally conservative — it catches common patterns
    (``> file``, ``tee file``, ``sed -i file``, ``cp`` / ``mv`` / ``install``
    destinations, ``python -c`` quoted paths, ``git apply`` / ``patch``
    ``+++`` targets) but does not attempt to parse arbitrary shell syntax.
    """
    candidates = set()
    for regex in (_SHELL_REDIRECT, _SHELL_TEE, _SHELL_SED_I, _SHELL_CP_MV):
        for m in regex.finditer(command):
            raw = m.group("path").strip().strip("'\"")
            if raw and not raw.startswith("/dev/") and raw != "/dev/null":
                candidates.add(raw)

    def _quoted_strings():
        for regex in (_SHELL_SINGLE, _SHELL_DOUBLE):
            for m in regex.finditer(command):
                yield m.group(1).strip()

    if _SHELL_PYTHON_C.search(command):
        for raw in _quoted_strings():
            if _looks_like_path(raw):
                candidates.add(raw)

    base = Path(cwd).resolve() if cwd else project_root
    if _SHELL_PATCH_CMD.search(command):
        for raw in _quoted_strings():
            if raw.endswith((".diff", ".patch")):
                candidates.update(_paths_from_patch_file(raw, base))
            elif _looks_like_path(raw):
                candidates.add(raw)
        for m in _SHELL_PATCH_FILE.finditer(command):
            candidates.update(_paths_from_patch_file(m.group("path"), base))

    for raw in candidates:
        try:
            p = Path(raw)
            p = (base / raw).resolve() if not p.is_absolute() else p.resolve()
            rel = _compute_rel_path(str(p), project_root, wt_root, main_root)
            # Yield every target, including ones outside the project root: the
            # guard's boundary rule must see out-of-root writes (``echo x >
            # /tmp/f``) so they are denied just like the Write tool's, and the
            # redline rules still match on the basename of outside paths.
            yield (rel, str(p))
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Agent / phase inference
# ---------------------------------------------------------------------------

# Glob patterns that identify test files.
_TEST_FILE_GLOBS = [
    "**/test/**",
    "**/tests/**",
    "**/__tests__/**",
    "*_test.go",
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.test.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.js",
    "*.spec.jsx",
]


def is_test_file(rel_path):
    """Return ``True`` if *rel_path* looks like a test file."""
    return any(path_matches_glob(rel_path, pattern) for pattern in _TEST_FILE_GLOBS)


def is_user_agent_state(abs_path):
    """Return ``True`` when *abs_path* is user-level agent state, not project code.

    These stores live outside any single project yet must stay writable by
    agents: they are cross-project infrastructure, not a project's files.

    * ``~/.claude/`` — auto-memory, global rules, plugin configuration/data.
    * ``MEMORANT_ROOT`` — Memorant's vault (``memories/``, ``activity/``,
      ``source_docs/`` …). When unset, Memorant's default
      ``~/Documents/Memorant`` is used.

    A project-local ``<root>/.claude`` is inside the root and needs no
    exemption; that case is handled by the normal boundary check.
    """
    try:
        target = Path(abs_path).resolve()
        home = Path.home()
        roots = {(home / ".claude").resolve()}
        memorant = os.environ.get("MEMORANT_ROOT", "").strip()
        roots.add(
            (Path(memorant).expanduser() if memorant else home / "Documents" / "Memorant")
            .resolve()
        )
        return any(_is_relative_to(target, root) for root in roots)
    except (OSError, RuntimeError, ValueError):
        return False


def _is_relative_to(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_within_boundary(abs_path, project_root, cwd=None):
    """Return ``True`` when *abs_path* lies inside the session's project root.

    The boundary is the launch directory and everything beneath it ("drill
    down only, never up"): a workspace may span several repositories, so any
    path under the root is allowed, and any path outside it is refused.  This
    replaces the per-track directory checks — the model has no per-repo track
    gating, so there is no ``track`` argument.

    User-level agent state (``~/.claude`` for memory/rules/plugins, and
    Memorant's ``MEMORANT_ROOT`` vault) is exempt — it is cross-project
    infrastructure, not a project file, so it is never denied by a project's
    boundary.

    In a Claude subagent worktree, *abs_path* and the root are both mapped to
    the main workspace before comparing, so worktree paths match the main tree.

    Fail-open only when the boundary cannot be determined (unresolvable root).
    """
    if is_user_agent_state(abs_path):
        return True
    try:
        wt_root, main_root = detect_worktree(cwd) if cwd else (None, None)

        target = Path(abs_path).resolve()
        root = Path(project_root).resolve()

        if wt_root and main_root:
            target = Path(map_worktree_path(str(target), wt_root, main_root)).resolve()
            root = main_root.resolve()

        target.relative_to(root)
        return True
    except ValueError:
        return False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Dangerous Bash command detection
# ---------------------------------------------------------------------------

_DANGEROUS_CMD_PATTERNS = [
    (
        # Recursive delete aimed at the filesystem root, a home directory, or
        # a substitution result. The shape matters:
        #   ``/``  must be the whole path — ``/tmp/scratch`` is routine cleanup,
        #          and matching its leading slash blocked every temp cleanup.
        #   ``~`` / ``$HOME`` cover their subtrees too — deleting ``~/Documents``
        #          is as unrecoverable as deleting ``~`` itself.
        re.compile(
            r"\brm\s+(-[rRf]+\s+)+(?:/\s*$|/\*|~(?:/|\s|$)|\$HOME(?:/|\s|$)|\$\(.*\))"
        ),
        "Destructive recursive delete on system/home directory",
    ),
    (re.compile(r"\brm\s+(-[rRf]+\s+)+/\*"), "Destructive recursive delete on root"),
    (re.compile(r"\bmkfs\b", re.IGNORECASE), "Filesystem formatting command"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "Raw disk write via dd"),
    (re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE), "Direct write to block device"),
    (re.compile(r"\bgit\s+push\s+.*(-f|--force)\b", re.IGNORECASE), "Force push to git remote"),
    (re.compile(r"\bcurl\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE), "Piping remote script to shell"),
    (re.compile(r"\bwget\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE), "Piping remote script to shell"),
    (re.compile(r"\bnpm\s+publish\b", re.IGNORECASE), "Publishing package to registry"),
    (re.compile(r"\bdrop\s+table\b", re.IGNORECASE), "SQL DROP TABLE statement"),
]

# Bulk-destructive invocations (2026-11 audit). These discard work in one shot
# and matched none of the patterns above; recovering means re-doing the work.
#
# Anchored with ``match`` against a single shell segment, not searched in the
# whole command line: ``git reset --hard`` inside a quoted commit message is
# text, while the same words at the start of a segment are an invocation.
_BULK_CMD_PATTERNS = [
    (
        re.compile(r"git\s+checkout\s+(--\s+)?(\.|:/|\*)($|\s)"),
        "Discards all working-tree changes",
    ),
    (re.compile(r"git\s+reset\s+--hard\b", re.IGNORECASE), "Discards all commits and changes"),
    (re.compile(r"git\s+clean\s+-[a-z]*f", re.IGNORECASE), "Deletes all untracked files"),
    (re.compile(r"git\s+branch\s+-D\b"), "Force-deletes an unmerged branch"),
    (re.compile(r"find\b.*\s-delete\b"), "Recursive delete via find"),
    (re.compile(r"rsync\b.*\s--delete\b"), "Deletes destination files via rsync"),
    (re.compile(r"truncate\s+-s\s*0\b", re.IGNORECASE), "Truncates a file to zero bytes"),
]

# Command substitution executes its body wherever it appears, including inside
# double quotes, so the body is checked on its own.
_COMMAND_SUBSTITUTION = re.compile(r"\$\((.*?)\)|`(.*?)`", re.DOTALL)


def _shell_source_text(command):
    """Return the command with literal text a shell cannot execute removed:
    heredoc bodies and single-quoted strings.

    Without this, a commit message passed via ``-F -`` heredoc that merely
    *describes* a destructive command was blocked as if it ran it. Double
    quotes are kept, and command substitutions (``$(...)`` / backticks) are
    hoisted out first — they run even inside double quotes.
    """
    text = command or ""
    # Drop heredoc bodies FIRST: everything a heredoc carries is stdin, never
    # executed. Hoisting substitutions before this step made a markdown code
    # span inside a heredoc (`` `git checkout .` `` in a PR body) look like a
    # real command substitution.
    text = re.sub(
        r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1\s*(?:\n|$)", "\n", text, flags=re.DOTALL
    )
    # Single-quoted strings carry no expansion, so nothing in them executes.
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"'[^']*'", "''", text)
    # Only now hoist substitution bodies out of what survives: they run even
    # inside double quotes, so they must still be checked after the quoting
    # removal above would otherwise swallow them.
    for match in _COMMAND_SUBSTITUTION.finditer(text):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        text += "\n" + body
    return text


def check_dangerous_command(command):
    """Return a reason string if *command* matches a dangerous pattern,
    otherwise ``None``.

    Two passes, because the pattern sets answer different questions:

    * The original patterns run over the whole line — they are specific
      enough (``rm -rf /``, ``mkfs``, force-push) that a mention elsewhere is
      still worth flagging.
    * Bulk-destructive patterns run per shell segment and are anchored at the
      start, so a segment that only *mentions* ``git reset --hard`` (inside a
      quoted commit message) stays text while a real invocation after ``&&``
      is caught.
    """
    try:
        source = _shell_source_text(command)
        for pattern, reason in _DANGEROUS_CMD_PATTERNS:
            if pattern.search(source):
                return reason
        for segment in _split_shell_segments(source):
            for pattern, reason in _BULK_CMD_PATTERNS:
                if pattern.match(segment):
                    return reason
    except Exception:
        pass
    return None


_SHELL_CHAIN = re.compile(r"&&|\|\||[;|\n]")

# A segment may start with leading whitespace, a variable assignment, or a
# command wrapper (``sudo``/``env``/``time``). Anything before the command name
# is skipped so ``sudo git clean -fd`` still matches.
_SEGMENT_PREFIX = re.compile(r"^(?:\s*(?:sudo|env|time|exec)?\s*(?:[A-Za-z_]\w*=\S*\s+)*)+")


def _split_shell_segments(command):
    """Split a shell command line on ``&&``, ``||``, ``;``, ``|`` and newlines,
    then strip comment lines and leading wrappers."""
    segments = []
    for raw in _SHELL_CHAIN.split(command or ""):
        segment = raw.strip()
        if not segment or segment.startswith("#"):
            continue
        # Drop a trailing comment so ``git status  # not "git clean -fd"``
        # does not read as an invocation.
        segment = segment.split(" #", 1)[0].strip()
        if segment:
            segments.append(_SEGMENT_PREFIX.sub("", segment, count=1))
    return segments


# Credential markers that make an ``approval_required`` write worth asking
# about.  The path alone is a poor signal: editing ``config/app.yaml`` to bump
# a timeout is routine, while writing ``password: ...`` into it is not.
_CREDENTIAL_MARKER = re.compile(
    r"password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|access[_-]?key",
    re.IGNORECASE,
)

# Tool inputs whose text is what the tool is about to persist. For ``Edit`` and
# ``MultiEdit`` only the new content counts — matching the old text would make
# removing a secret look like adding one.
_CONTENT_FIELDS = {
    "Write": ("content",),
    "Edit": ("new_string",),
    "MultiEdit": ("edits",),
}


def content_carries_credential(tool_name, tool_input):
    """Return ``True`` when the tool call writes credential-looking content.

    Fail-open on absent content: tools that carry no inspected text (a large
    ``Edit`` payload that never surfaced ``new_string``, or an unknown tool)
    must not be *silently* allowed, so the caller decides.  Here ``False``
    means "no marker found in whatever content we could see".
    """
    try:
        if tool_name == "MultiEdit":
            for edit in tool_input.get("edits") or ():
                if isinstance(edit, dict) and _CREDENTIAL_MARKER.search(
                    str(edit.get("new_string", ""))
                ):
                    return True
            return False
        for field in _CONTENT_FIELDS.get(tool_name, ()):
            if _CREDENTIAL_MARKER.search(str(tool_input.get(field, ""))):
                return True
        return False
    except Exception:
        return False


def content_was_inspectable(tool_name, tool_input):
    """Return ``True`` when the tool call carried text we could inspect.

    ``Edit`` carries only the changed snippet, so the absence of a marker is
    weaker evidence than for a full ``Write``.  The guard keeps the
    conservative "ask" whenever no content was available to look at.
    """
    try:
        if tool_name == "MultiEdit":
            return bool(tool_input.get("edits"))
        return any(field in tool_input for field in _CONTENT_FIELDS.get(tool_name, ()))
    except Exception:
        return False


_GIT_COMMIT = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)


def is_git_commit(command):
    """Return ``True`` when *command* invokes ``git commit``.

    Delivery lifecycle runs the commit through the Bash tool so the guard hooks
    can audit it; this matcher lets the delivery phase gate on it.
    """
    try:
        return bool(_GIT_COMMIT.search(command))
    except Exception:
        return False
