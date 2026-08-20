#!/usr/bin/env python3
"""Idempotent migration from the legacy manifest to project/task state."""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Optional


class MigrationConflict(RuntimeError):
    """Raised when generated state already exists with different content."""


def _scalar(content: str, key: str, section: Optional[str] = None) -> Optional[str]:
    active = section is None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if section is not None:
            if indent == 0 and stripped.endswith(":"):
                active = stripped[:-1] == section
                continue
            if not active or indent < 2:
                continue
        prefix = f"{key}:"
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
            if value in {"null", "~"}:
                return None
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1].replace('\\"', '"')
            return value.strip("'")
    return None


def _list(content: str, key: str, section: Optional[str] = None) -> list[str]:
    active = section is None
    values: list[str] = []
    collecting = False
    for line in content.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if section is not None and indent == 0 and stripped.endswith(":"):
            active = stripped[:-1] == section
            collecting = False
            continue
        if not active:
            continue
        if stripped.startswith(f"{key}:"):
            collecting = True
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                return [item.strip().strip('"\'') for item in inline[1:-1].split(",") if item.strip()]
            continue
        if collecting and stripped.startswith("-") and indent >= 2:
            values.append(stripped[1:].strip().strip('"\''))
        elif collecting and stripped and indent < 2:
            collecting = False
    return values


def _yaml(value: Optional[str]) -> str:
    if value is None:
        return "null"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _git_value(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _write_if_absent(path: Path, content: str) -> bool:
    if path.exists():
        if path.read_text(encoding="utf-8", errors="replace") != content:
            raise MigrationConflict(f"migration target differs: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return True


def migrate_legacy_project(root: Path) -> dict[str, object]:
    """Create project.yaml and a read-only legacy task without changing manifest."""
    root = root.resolve()
    devflow = root / ".devflow"
    manifest = devflow / "manifest.yaml"
    if not manifest.is_file():
        return {"status": "not_applicable", "created": []}

    content = manifest.read_text(encoding="utf-8", errors="replace")
    project_name = _scalar(content, "name", "project") or root.name
    created_at = _scalar(content, "created_at", "project")
    category = _scalar(content, "category", "project")
    confidence = _scalar(content, "category_confidence", "project")
    ambiguous = _scalar(content, "category_ambiguous", "project") or "false"
    capabilities = _list(content, "capabilities", "project")
    adapter_name = _scalar(content, "name", "adapter") or "claude-code"
    adapter_capability = _scalar(content, "capability", "adapter") or "hard"
    workspace_root = _scalar(content, "root", "workspace") or str(root)
    branch = _git_value(root, "branch", "--show-current")
    commit = _git_value(root, "rev-parse", "HEAD")
    phase = _scalar(content, "current_phase", "project") or "idle"
    kind = _scalar(content, "work_type", "project") or "feature"
    description = _scalar(content, "task_description", "classify") or ""

    project_yaml = (
        "schema_version: 1\n\nproject:\n"
        f"  name: {_yaml(project_name)}\n"
        f"  created_at: {_yaml(created_at)}\n"
        "  category:\n"
        f"    primary: {_yaml(category)}\n"
        f"    confidence: {_yaml(confidence)}\n"
        f"    ambiguous: {_yaml(ambiguous)}\n"
        "    evidence: []\n"
        f"  capabilities: [{', '.join(_yaml(item) for item in capabilities)}]\n\n"
        "workspace:\n"
        f"  root: {_yaml(workspace_root)}\n"
        "  contract_path: \".devflow/contracts\"\n"
        "  docs_path: \"docs\"\n"
        "  rules_path: \".devflow/rules\"\n\n"
        "platforms:\n"
        f"  supported: [{_yaml(adapter_name)}]\n"
        f"  default: {_yaml(adapter_name)}\n\n"
        "safety:\n  redlines_path: \".devflow/redlines.yaml\"\n\n"
        "adapter_snapshot:\n"
        f"  name: {_yaml(adapter_name)}\n"
        f"  capability: {_yaml(adapter_capability)}\n"
    )
    task_yaml = (
        "schema_version: 1\n\ntask:\n"
        "  id: \"legacy\"\n  slug: \"legacy\"\n"
        f"  kind: {_yaml(kind)}\n"
        f"  description: {_yaml(description)}\n"
        f"  current_phase: {_yaml(phase)}\n"
        f"  status: {_yaml('done' if phase == 'done' else 'active')}\n\n"
        "git:\n"
        f"  base_ref: {_yaml(branch or 'HEAD')}\n"
        f"  base_commit: {_yaml(commit)}\n"
        f"  branch: {_yaml(branch)}\n"
        f"  worktree: {_yaml(str(root))}\n\n"
        "isolation:\n  mode: \"legacy\"\n  isolated: false\n\n"
        "legacy:\n  source_manifest: \".devflow/manifest.yaml\"\n  read_only: true\n"
    )
    created: list[str] = []
    if _write_if_absent(devflow / "project.yaml", project_yaml):
        created.append(".devflow/project.yaml")
    if _write_if_absent(devflow / "tasks" / "legacy" / "task.yaml", task_yaml):
        created.append(".devflow/tasks/legacy/task.yaml")
    marker = "schema_version: 1\nstatus: completed\nsource: .devflow/manifest.yaml\n"
    if _write_if_absent(devflow / "migration.yaml", marker):
        created.append(".devflow/migration.yaml")
    return {"status": "migrated" if created else "already_migrated", "created": created}
