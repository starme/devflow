#!/usr/bin/env python3
"""Small stdlib bridge for Codex core audit/redline hooks.

v2 (ADR-0005): the runtime ``context.json`` writer is retired along with the
role-agent dispatch — task state is self-sufficient in ``.devflow/task.yaml``.
This bridge keeps the platform-neutral hook payload builder and runner plus
the soft-capability warning.
"""
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
