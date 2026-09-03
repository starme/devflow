#!/usr/bin/env python3
"""Regression tests for DevFlow lifecycle hook continuation behavior."""
import json
import subprocess
import sys
import tempfile
import unittest
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


class DevFlowHookStopTest(unittest.TestCase):
    """Stop-hook continuation behaviour across legacy and isolated-task layouts."""

    @staticmethod
    def write_task_yaml(devflow: Path, phase: str) -> None:
        """Minimal task.yaml matching the isolated-worktree layout produced by
        core/orchestrator/task_state.py: the phase nests under ``task:``."""
        (devflow / "task.yaml").write_text(
            "schema_version: 1\n"
            "task:\n"
            "  id: \"test-task\"\n"
            "  slug: \"test-task\"\n"
            "  kind: \"feature\"\n"
            "  description: \"test\"\n"
            f"  current_phase: \"{phase}\"\n"
            "  status: \"active\"\n",
            encoding="utf-8",
        )

    def test_auto_phase_blocks_stop_for_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: testing\n", encoding="utf-8"
            )

            output = run_hook(root)

            self.assertEqual(output["decision"], "block")
            self.assertIn("/devflow next", output["reason"])

    def test_auto_phase_blocks_stop_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "testing")

            output = run_hook(root)

            self.assertEqual(output["decision"], "block")
            self.assertIn("/devflow next", output["reason"])

    def test_gate_phase_allows_stop_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "gate_prd")

            output = run_hook(root)

            self.assertEqual(output, {})

    def test_stop_hook_does_not_loop_when_already_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: testing\n", encoding="utf-8"
            )

            output = run_hook(root, stop_hook_active=True)

            self.assertEqual(output, {})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: gate_prd\n", encoding="utf-8"
            )

            output = run_hook(root)

            self.assertEqual(output, {})

    def test_stop_hook_no_loop_from_task_yaml_when_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "testing")

            output = run_hook(root, stop_hook_active=True)

            self.assertEqual(output, {})


if __name__ == "__main__":
    unittest.main()
