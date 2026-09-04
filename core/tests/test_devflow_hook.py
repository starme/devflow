#!/usr/bin/env python3
"""Regression tests for DevFlow lifecycle hook continuation behavior."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parents[2] / "hooks" / "devflow_hook.py"


def run_event(root: Path, event: str, **extra) -> subprocess.CompletedProcess:
    payload = {
        "hook_event_name": event,
        "cwd": str(root),
        **extra,
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=root,
        check=True,
    )


def run_hook(root: Path, stop_hook_active: bool = False) -> dict:
    result = run_event(root, "Stop", stop_hook_active=stop_hook_active)
    return json.loads(result.stdout)


def _load_hook_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("devflow_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
            self.assertIn("Do not stop", output["reason"])
            self.assertIn("do not wait for /devflow next", output["reason"])

    def test_auto_phase_blocks_stop_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "testing")

            output = run_hook(root)

            self.assertEqual(output["decision"], "block")
            self.assertIn("Do not stop", output["reason"])
            self.assertIn("do not wait for /devflow next", output["reason"])

    def test_gate_phase_allows_stop_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "gate_prd")

            output = run_hook(root)

            self.assertEqual(output, {})

    def test_auto_phase_keeps_blocking_when_stop_already_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: testing\n", encoding="utf-8"
            )

            output = run_hook(root, stop_hook_active=True)

            self.assertEqual(output["decision"], "block")
            self.assertIn("Do not stop", output["reason"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: gate_prd\n", encoding="utf-8"
            )

            output = run_hook(root)

            self.assertEqual(output, {})

    def test_auto_phase_keeps_blocking_from_task_yaml_when_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "testing")

            output = run_hook(root, stop_hook_active=True)

            self.assertEqual(output["decision"], "block")
            self.assertIn("Do not stop", output["reason"])

    def test_delivery_phase_allows_stop_for_user_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "delivery")

            output = run_hook(root)

            self.assertEqual(output, {})


class DevFlowHookLifecycleTest(unittest.TestCase):
    """SessionStart / UserPrompt / PreCompact plus read-only legacy lookup."""

    @staticmethod
    def write_task_yaml(devflow: Path, phase: str) -> None:
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

    def test_session_start_reads_kind_and_phase_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "development")

            data = json.loads(run_event(root, "SessionStart").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("type: feature", ctx)
            self.assertIn("phase: development", ctx)
            self.assertIn("next Gate", ctx)
            self.assertNotIn("/devflow next to continue", ctx)

    def test_user_prompt_flags_delivery_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "delivery")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("delivery", ctx)
            self.assertIn("Awaiting", ctx)

    def test_user_prompt_stays_quiet_in_auto_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "testing")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            self.assertEqual(data, {})

    def test_pre_compact_preserves_task_state_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "architecture")

            text = run_event(root, "PreCompact").stdout
            self.assertIn("[DevFlow State", text)
            self.assertIn("Phase: architecture", text)
            self.assertIn("current_phase:", text)

    def test_legacy_manifest_lookup_does_not_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: testing\n  work_type: feature\n",
                encoding="utf-8",
            )

            data = json.loads(run_event(root, "SessionStart").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("phase: testing", ctx)
            self.assertFalse((devflow / "project.yaml").exists())
            self.assertFalse((devflow / "migration.yaml").exists())
            self.assertFalse((devflow / "tasks").exists())


class NewestPluginDirTest(unittest.TestCase):
    def test_prefers_higher_version_over_older_mtime(self) -> None:
        hook = _load_hook_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            older = Path(temp_dir) / "0.9.0"
            newer = Path(temp_dir) / "1.2.0"
            older.mkdir()
            newer.mkdir()
            os.utime(older, (2_000_000_000, 2_000_000_000))
            os.utime(newer, (1_000_000_000, 1_000_000_000))
            self.assertEqual(hook._newest_dir([str(older), str(newer)]), str(newer))


if __name__ == "__main__":
    unittest.main()
