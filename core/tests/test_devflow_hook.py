#!/usr/bin/env python3
"""Regression tests for DevFlow lifecycle hook continuation behavior."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


HOOK = Path(__file__).resolve().parents[2] / "hooks" / "devflow_hook.py"


def run_hook(root: Path, stop_hook_active: bool = False) -> dict:
    payload = {
        "hook_event_name": "Stop",
        "cwd": str(root),
        "stop_hook_active": stop_hook_active,
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=root,
        check=True,
    )
    return json.loads(result.stdout)


def test_auto_phase_blocks_stop_for_continuation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        (devflow / "manifest.yaml").write_text(
            "project:\n  current_phase: testing\n", encoding="utf-8"
        )

        output = run_hook(root)

        assert output["decision"] == "block"
        assert "/devflow next" in output["reason"]


def test_stop_hook_does_not_loop_when_already_active() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        (devflow / "manifest.yaml").write_text(
            "project:\n  current_phase: testing\n", encoding="utf-8"
        )

        output = run_hook(root, stop_hook_active=True)

        assert output == {}
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        (devflow / "manifest.yaml").write_text(
            "project:\n  current_phase: gate_prd\n", encoding="utf-8"
        )

        output = run_hook(root)

        assert output == {}
