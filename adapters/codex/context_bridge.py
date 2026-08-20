#!/usr/bin/env python3
"""Small stdlib bridge for Codex context and core audit hooks."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Dict, Union


SOFT_CAPABILITY_WARNING = (
    "Codex adapter capability is soft: generic pre-tool file-write interception "
    "is not verified; use Codex approvals and post-action audit logging."
)


def write_context(project_root: Union[str, Path], context: Dict[str, object]) -> Path:
    """Persist task-scoped runtime context consumed by core hooks."""
    root = Path(project_root).resolve()
    task_root = Path(str(context.get("task_root", root / ".devflow"))).resolve()
    context_path = task_root / "context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return context_path


def build_core_payload(tool_name: str, tool_input: Dict[str, object], cwd: Union[str, Path]) -> str:
    """Build the platform-neutral payload accepted by core hooks."""
    return json.dumps({"tool_name": tool_name, "tool_input": tool_input, "cwd": str(Path(cwd).resolve())})


def run_core_hook(script: Union[str, Path], payload: str, cwd: Union[str, Path]) -> subprocess.CompletedProcess:
    """Run a core hook and return its protocol result."""
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


def soft_warning() -> str:
    """Return the explicit warning required for Codex soft mode."""
    return SOFT_CAPABILITY_WARNING
