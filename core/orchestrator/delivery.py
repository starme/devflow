#!/usr/bin/env python3
"""DevFlow delivery lifecycle: read-only probes and delivery sub-state.

This module is intentionally free of side effects on the repository. It never
runs ``git commit`` / ``git push`` / ``gh pr create`` or any other mutating
command — the Manager executes those through the Bash tool so every write is
audited by the guard hooks.

Responsibilities:

1. Probe delivery capability: ``gh_available``, ``branch_pushed``,
   ``remote_name`` and ``dirty_files``.
2. Declare the delivery artifact whitelist ``DELIVERY_ARTIFACT_FILES``
   (kept in sync with ``core/hooks/devflow_guard_common.py``).
3. Read/write the independent ``.devflow/delivery.yaml`` sub-state, referenced
   from ``task.yaml``'s ``artifacts`` section, so delivery progress survives
   session interruptions and is idempotent on resume.

All probes are fail-safe: when ``git``/``gh`` are missing or unauthenticated,
they return safe defaults (``False``/``None``/``[]``) instead of raising.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Optional


# Delivery artifact whitelist.  Must stay in sync with
# ``_DEVFLOW_ARTIFACT_FILES`` in ``core/hooks/devflow_guard_common.py`` so the
# guard hooks permit the same files the delivery flow may commit.
DELIVERY_ARTIFACT_FILES = frozenset({
    ".devflow/scope.yaml",
    ".devflow/prd.md",
    ".devflow/architecture.md",
    ".devflow/diagnosis.md",
    ".devflow/acceptance-report.md",
    ".devflow/acceptance-scenarios.md",
    ".devflow/test-report.md",
    ".devflow/task-report.md",
    ".devflow/backend-task-report.md",
    ".devflow/frontend-task-report.md",
    ".devflow/pr.md",
    ".devflow/delivery.yaml",
})

# Files that are produced by the Manager/agents but must never enter the
# delivery commit.
DELIVERY_SKIP_FILES = frozenset({
    ".devflow/context.json",
})

_DELIVERY_STATE_FILE = ".devflow/delivery.yaml"


def _run(args: list[str], root: Optional[Path] = None) -> Optional[str]:
    """Run a read-only command and return stripped stdout, or ``None`` on any
    failure (fail-safe: probes never raise)."""
    try:
        result = subprocess.run(
            args, cwd=root, text=True, capture_output=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git(root: Optional[Path], *args: str) -> Optional[str]:
    return _run(["git", *args], root=root)


def gh_available(root: Optional[Path] = None) -> bool:
    """Return ``True`` if the ``gh`` CLI exists and is authenticated.

    Uses ``gh auth status`` exit code only — ``gh api`` would touch the
    network and is deliberately avoided.  ``gh auth status`` succeeds (exit 0)
    only when gh is installed *and* authenticated; any other outcome — gh
    missing, gh unauthenticated, or an empty result — is ``False``.
    """
    probe = _run(["gh", "auth", "status"], root=root)
    if probe is None:
        return False
    # A successful ``gh auth status`` always emits an auth summary; an empty
    # stdout means the probe did not actually confirm authentication.
    return bool(probe.strip())


def remote_name(root: Optional[Path] = None) -> Optional[str]:
    """Return the remote name for the current branch, or ``None`` if no
    upstream is configured or git is unavailable."""
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not upstream:
        return None
    # ``@{upstream}`` yields ``<remote>/<branch>``.
    return upstream.split("/", 1)[0] or None


def branch_pushed(root: Optional[Path] = None) -> bool:
    """Return ``True`` if the current branch already has an upstream remote."""
    return remote_name(root) is not None


def dirty_files(root: Optional[Path] = None) -> list[str]:
    """Return the list of dirty paths from ``git status --porcelain``.

    Each entry is the raw porcelain line (``XY path``); an empty list means a
    clean working tree or an unavailable git.
    """
    output = _git(root, "status", "--porcelain")
    if not output:
        return []
    return [line for line in output.splitlines() if line.strip()]


@dataclass(frozen=True)
class DeliveryState:
    """Independent delivery sub-state persisted to ``.devflow/delivery.yaml``.

    Every field is independently determinable so ``/devflow next`` can resume
    idempotently — already-completed steps are skipped, never repeated.
    """
    commit: Optional[str] = None
    pushed: bool = False
    remote: str = "origin"
    pr_url: Optional[str] = None
    pr_title: Optional[str] = None
    worktree_removed: bool = False
    branch_deleted: bool = False
    returned_to_main: bool = False


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def _yaml_quote(value: Optional[str]) -> str:
    if value is None:
        return "null"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_delivery_yaml(state: DeliveryState) -> str:
    """Render the delivery sub-state as human-readable YAML."""
    return (
        "schema_version: 1\n"
        "\n"
        "delivery:\n"
        f"  commit: {_yaml_quote(state.commit)}\n"
        f"  pushed: {_yaml_bool(state.pushed)}\n"
        f"  remote: {_yaml_quote(state.remote)}\n"
        f"  pr_url: {_yaml_quote(state.pr_url)}\n"
        f"  pr_title: {_yaml_quote(state.pr_title)}\n"
        f"  worktree_removed: {_yaml_bool(state.worktree_removed)}\n"
        f"  branch_deleted: {_yaml_bool(state.branch_deleted)}\n"
        f"  returned_to_main: {_yaml_bool(state.returned_to_main)}\n"
    )


def _read_scalar(content: str, key: str) -> Optional[str]:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            value = stripped.split(":", 1)[1].strip()
            if value in {"null", "~"}:
                return None
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            return value
    return None


def _read_bool(content: str, key: str) -> bool:
    value = _read_scalar(content, key)
    return value == "true"


def load_delivery_state(path: Path) -> DeliveryState:
    """Load the delivery sub-state, returning defaults when absent or
    malformed (fail-safe)."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return DeliveryState()
    return DeliveryState(
        commit=_read_scalar(content, "commit"),
        pushed=_read_bool(content, "pushed"),
        remote=_read_scalar(content, "remote") or "origin",
        pr_url=_read_scalar(content, "pr_url"),
        pr_title=_read_scalar(content, "pr_title"),
        worktree_removed=_read_bool(content, "worktree_removed"),
        branch_deleted=_read_bool(content, "branch_deleted"),
        returned_to_main=_read_bool(content, "returned_to_main"),
    )


def save_delivery_state(root: Path, state: DeliveryState) -> Path:
    """Persist the delivery sub-state to ``<root>/.devflow/delivery.yaml``."""
    devflow = root / ".devflow"
    devflow.mkdir(parents=True, exist_ok=True)
    path = devflow / "delivery.yaml"
    path.write_text(render_delivery_yaml(state), encoding="utf-8")
    return path
