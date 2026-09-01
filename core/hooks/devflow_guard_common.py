#!/usr/bin/env python3
"""Shared utilities for DevFlow guard hooks (redline-guard, audit-log).

No third-party dependencies. All functions fail-safe: they return empty
defaults rather than raising, so hooks never block the user on internal errors.
"""
import json
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Project root / context discovery
# ---------------------------------------------------------------------------

def find_project_root(cwd=None):
    """Walk up from *cwd* to find a directory containing ``.devflow/``.

    Returns the project root as a :class:`Path`, or ``None``.

    Worktree-aware: when *cwd* is inside a Claude Code isolated worktree,
    any ``.devflow/`` that the agent may have created *inside* the worktree
    is skipped — the authoritative project root is the main workspace
    (which contains the real manifest, redlines, and context).
    """
    try:
        start = Path(cwd) if cwd else Path.cwd()
        if not start.is_absolute():
            start = start.resolve()

        # A DevFlow task worktree is itself an authoritative project root. Its
        # task state must never fall back to another worktree's context.
        for parent in [start] + list(start.parents):
            if (parent / ".devflow" / "task.yaml").is_file():
                return parent

        # In a Claude subagent worktree, the main workspace root is known directly.
        wt_root, main_root = detect_worktree(str(start))
        if wt_root and main_root and (main_root / ".devflow").is_dir():
            return main_root

        for parent in [start] + list(start.parents):
            if (parent / ".devflow").is_dir():
                return parent
    except Exception:
        pass
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
        for parent in [p] + list(p.parents):
            if (parent / ".devflow" / "task.yaml").is_file():
                project_root = parent
                while project_root.parent != project_root and project_root.name != ".devflow-worktrees":
                    project_root = project_root.parent
                if project_root.name == ".devflow-worktrees":
                    return p if p == parent else parent, project_root.parent
        parts = p.parts
        for i in range(len(parts) - 1):
            if parts[i] == ".claude" and i + 1 < len(parts) and parts[i + 1] == "worktrees":
                if i + 2 < len(parts) and parts[i + 2].startswith("agent-"):
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

    # 3. Claude Code cache fallback.
    try:
        home = Path.home()
        for p in (home / ".claude" / "plugins" / "cache").glob("*/devflow/*"):
            core = p / "core"
            if (core / "templates" / "redlines.yaml").is_file():
                return core
    except Exception:
        pass

    return None


def _parse_manifest_workspace(project_root):
    """Parse workspace paths from ``.devflow/manifest.yaml``.

    Returns a dict with ``root``, ``backend``, ``frontend`` keys.
    This is a *minimal* YAML reader — it only extracts the fields the
    guard hooks need, without requiring PyYAML.
    """
    ws = {"root": str(project_root), "backend": "", "frontend": ""}
    try:
        manifest = project_root / ".devflow" / "manifest.yaml"
        if not manifest.is_file():
            return ws

        content = manifest.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        in_workspace = False
        ws_indent = 0
        current_subkey = None

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip())

            # Top-level workspace: section
            if indent == 0 and stripped == "workspace:":
                in_workspace = True
                ws_indent = 0
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

    Merges two sources (context.json takes priority for runtime fields):

    1. ``.devflow/context.json`` — written by the orchestrator during a run
       (provides ``run_id``, ``current_agent``, ``current_phase``).
    2. ``.devflow/manifest.yaml`` — project configuration (provides
       ``workspace`` root/backend/frontend paths, ``current_phase`` fallback).

    Always returns at least ``{"workspace": {...}}`` so boundary checks
    can function.
    """
    ctx = {}

    # 1. Load context.json (runtime state written by the orchestrator)
    try:
        ctx_file = project_root / ".devflow" / "context.json"
        if ctx_file.is_file():
            ctx = json.loads(ctx_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        ctx = {}

    # 2. Enrich from manifest.yaml (workspace paths are the critical piece)
    manifest_ws = _parse_manifest_workspace(project_root)
    if "workspace" not in ctx or not isinstance(ctx.get("workspace"), dict):
        ctx["workspace"] = manifest_ws
    else:
        # Merge — manifest fills in any missing keys
        for k, v in manifest_ws.items():
            if k not in ctx["workspace"] or not ctx["workspace"][k]:
                ctx["workspace"][k] = v

    # 3. Phase fallback
    if not ctx.get("current_phase"):
        phase = _parse_manifest_phase(project_root)
        if phase:
            ctx["current_phase"] = phase

    return ctx


_EMPTY_REDLINES = {
    "forbidden": [],
    "forbidden_negations": [],
    "protected": [],
    "protected_negations": [],
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
            if key in result:
                section = key
            else:
                section = None
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
            # Character class – find closing ]
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
                cls = pattern[i + 1:j]
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
    if regex.match(basename):
        return True
    return False


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
    for neg in negations:
        if path_matches_glob(rel_path, neg):
            return False
    return True


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Files under .devflow/ that agents are allowed to write *even when outside
# their track boundary*.  This covers process artifacts (reports, scope, runs)
# that any agent may need to produce.  Contracts are intentionally excluded —
# only the architect (who has no track boundary) writes them.
_DEVFLOW_ARTIFACT_PREFIXES = (
    ".devflow/runs/",
    ".devflow/impact-analysis/",
    ".devflow/sessions/",
    ".devflow/tasks/",
)
_DEVFLOW_ARTIFACT_FILES = frozenset({
    ".devflow/scope.yaml",
    ".devflow/diagnosis.md",
    ".devflow/architecture.md",
    ".devflow/prd.md",
    ".devflow/backend-task-report.md",
    ".devflow/frontend-task-report.md",
    ".devflow/test-report.md",
    ".devflow/task-report.md",
    ".devflow/acceptance-scenarios.md",
    ".devflow/acceptance-report.md",
    ".devflow/pr.md",
    ".devflow/delivery.yaml",
})

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
        for prefix in _DEVFLOW_ARTIFACT_PREFIXES:
            if rel_path.startswith(prefix):
                return True
        return False
    return False


def to_rel_path(file_path, project_root):
    """Resolve *file_path* against the project root and return a forward-slash
    relative path string."""
    try:
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = (project_root / fp).resolve()
        else:
            fp = fp.resolve()
        rel = fp.relative_to(project_root.resolve())
        return str(rel).replace(os.sep, "/")
    except Exception:
        # Path is outside project root – return absolute as-is
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
_SHELL_REDIRECT = re.compile(
    r"(?:>>?>)\s*(?P<path>[^\s;|&<>]+)"
)
_SHELL_TEE = re.compile(
    r"\btee\s+(?:-[a-zA-Z]+\s+)*(?P<path>[^\s;|&<>]+)"
)
_SHELL_SED_I = re.compile(
    r"\bsed\s+-i\b(?:\s+''|\"\"|\s+'[^']*'|\s+\"[^\"]*\")?\s+"
    r"(?:-[eE]\s+[^']+?\s+)*(?P<path>[^\s;|&<>]+)"
)


def _extract_shell_write_targets(command, project_root, cwd=None,
                                 wt_root=None, main_root=None):
    """Best-effort extraction of file paths that a Bash command writes to.

    Yields ``(rel_path, abs_path)`` tuples for targets inside the project.
    This is intentionally conservative — it catches common patterns
    (``> file``, ``tee file``, ``sed -i file``) but does not attempt to
    parse arbitrary shell syntax.
    """
    candidates = set()
    for regex in (_SHELL_REDIRECT, _SHELL_TEE, _SHELL_SED_I):
        for m in regex.finditer(command):
            raw = m.group("path").strip().strip("'\"")
            if raw and not raw.startswith("/dev/") and raw != "/dev/null":
                candidates.add(raw)

    base = Path(cwd).resolve() if cwd else project_root
    for raw in candidates:
        try:
            p = Path(raw)
            if not p.is_absolute():
                p = (base / raw).resolve()
            else:
                p = p.resolve()
            rel = _compute_rel_path(str(p), project_root, wt_root, main_root)
            # Only include targets inside project root
            if not rel.startswith("/"):
                yield (rel, str(p))
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Agent / phase inference
# ---------------------------------------------------------------------------

# Glob patterns that identify test files.
_TEST_FILE_GLOBS = [
    "**/test/**", "**/tests/**", "**/__tests__/**",
    "*_test.go",
    "*.test.ts", "*.test.tsx", "*.test.js", "*.test.jsx",
    "*.spec.ts", "*.spec.tsx", "*.spec.js", "*.spec.jsx",
]


def is_test_file(rel_path):
    """Return ``True`` if *rel_path* looks like a test file."""
    for pattern in _TEST_FILE_GLOBS:
        if path_matches_glob(rel_path, pattern):
            return True
    return False


def infer_track(cwd, workspace):
    """Infer which track an agent is working on based on its cwd.

    Returns ``"backend"``, ``"frontend"``, or ``None`` (root / unknown).

    Works in both normal and worktree modes: when *cwd* is inside a Claude
    Code worktree, the worktree prefix is stripped before comparing against
    workspace paths so that ``.../agent-xxx/server/`` correctly maps to the
    ``server`` backend directory.
    """
    if not workspace or not cwd:
        return None
    try:
        wt_root, main_root = detect_worktree(cwd)
        cwd_path = Path(cwd).resolve()
        root = Path(workspace.get("root", "")).resolve()

        # In worktree mode, workspace.root points at the main workspace but
        # cwd is inside the worktree.  Map cwd to its main-workspace
        # equivalent before checking track membership.
        if wt_root and main_root:
            cwd_path = Path(map_worktree_path(str(cwd_path), wt_root, main_root))
            root = main_root

        backend = workspace.get("backend", "")
        frontend = workspace.get("frontend", "")

        if backend:
            be_path = (root / backend).resolve() if not Path(backend).is_absolute() else Path(backend).resolve()
            try:
                cwd_path.relative_to(be_path)
                return "backend"
            except ValueError:
                pass

        if frontend:
            fe_path = (root / frontend).resolve() if not Path(frontend).is_absolute() else Path(frontend).resolve()
            try:
                cwd_path.relative_to(fe_path)
                return "frontend"
            except ValueError:
                pass
    except Exception:
        pass
    return None


def is_within_boundary(abs_path, workspace, track, cwd=None):
    """Check whether *abs_path* is within the allowed workspace boundary for
    the given *track*.  Returns ``True`` when allowed or when the boundary
    cannot be determined (fail-open).

    When *cwd* is inside a worktree, *abs_path* is mapped to its main-workspace
    equivalent so that the relative track paths in the workspace config match.
    """
    if not track or not workspace:
        return True
    try:
        wt_root, main_root = detect_worktree(cwd) if cwd else (None, None)

        target = Path(abs_path).resolve()
        root = Path(workspace.get("root", "")).resolve()

        if wt_root and main_root:
            target = Path(map_worktree_path(str(target), wt_root, main_root))
            root = main_root

        track_dir = workspace.get(track, "")
        if not track_dir:
            return True
        track_path = (root / track_dir).resolve() if not Path(track_dir).is_absolute() else Path(track_dir).resolve()
        target.relative_to(track_path)
        return True
    except ValueError:
        return False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Dangerous Bash command detection
# ---------------------------------------------------------------------------

_DANGEROUS_CMD_PATTERNS = [
    (re.compile(r"\brm\s+(-[rRf]+\s+)+(/|~|\$HOME|/\*|\$\(.*\))", re.IGNORECASE),
     "Destructive recursive delete on system/home directory"),
    (re.compile(r"\brm\s+-rf\s+/\*"),
     "Destructive recursive delete on root"),
    (re.compile(r"\bmkfs\b", re.IGNORECASE),
     "Filesystem formatting command"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE),
     "Raw disk write via dd"),
    (re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
     "Direct write to block device"),
    (re.compile(r"\bgit\s+push\s+.*(-f|--force)\b", re.IGNORECASE),
     "Force push to git remote"),
    (re.compile(r"\bcurl\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE),
     "Piping remote script to shell"),
    (re.compile(r"\bwget\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE),
     "Piping remote script to shell"),
    (re.compile(r"\bnpm\s+publish\b", re.IGNORECASE),
     "Publishing package to registry"),
    (re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
     "SQL DROP TABLE statement"),
]


def check_dangerous_command(command):
    """Return a reason string if *command* matches a dangerous pattern,
    otherwise ``None``."""
    try:
        for pattern, reason in _DANGEROUS_CMD_PATTERNS:
            if pattern.search(command):
                return reason
    except Exception:
        pass
    return None
