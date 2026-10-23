#!/usr/bin/env python3
"""Regression tests for DevFlow lifecycle hook hint behavior.

v2 (ADR-0005): hooks inform, never block. The Stop event is not registered
and must stay a no-op even if invoked directly.
"""

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


def _load_hook_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("devflow_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DevFlowHookStopNeverBlocksTest(unittest.TestCase):
    """ADR-0005: the block-on-Stop behavior is gone for good."""

    @staticmethod
    def write_task_yaml(devflow: Path, phase: str) -> None:
        (devflow / "task.yaml").write_text(
            "schema_version: 2\n"
            "task:\n"
            '  id: "test-task"\n'
            '  slug: "test-task"\n'
            '  kind: "feature"\n'
            '  description: "test"\n'
            f'  current_phase: "{phase}"\n'
            '  status: "active"\n',
            encoding="utf-8",
        )

    def test_stop_event_is_noop_even_in_working_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "working")

            output = json.loads(run_event(root, "Stop").stdout)
            self.assertEqual(output, {})

    def test_stop_event_is_noop_for_legacy_auto_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "manifest.yaml").write_text(
                "project:\n  current_phase: testing\n", encoding="utf-8"
            )

            output = json.loads(run_event(root, "Stop").stdout)
            self.assertEqual(output, {})

    def test_hook_module_has_no_block_emitter(self) -> None:
        hook = _load_hook_module()
        self.assertFalse(hasattr(hook, "emit_stop_block"))
        self.assertFalse(hasattr(hook, "handle_stop"))


class DevFlowHookLifecycleTest(unittest.TestCase):
    """SessionStart / UserPrompt / PreCompact hint behavior (v2 statuses)."""

    @staticmethod
    def write_task_yaml(devflow: Path, phase: str) -> None:
        (devflow / "task.yaml").write_text(
            "schema_version: 2\n"
            "task:\n"
            '  id: "test-task"\n'
            '  slug: "test-task"\n'
            '  kind: "feature"\n'
            '  description: "test"\n'
            f'  current_phase: "{phase}"\n'
            '  status: "active"\n',
            encoding="utf-8",
        )

    def test_session_start_reads_kind_and_phase_from_task_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "working")

            data = json.loads(run_event(root, "SessionStart").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("type: feature", ctx)
            self.assertIn("phase: working", ctx)
            self.assertIn("Gates", ctx)

    def test_user_prompt_flags_deliver_confirm_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "deliver_confirm")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("deliver_confirm", ctx)
            self.assertIn("Awaiting", ctx)

    def test_user_prompt_flags_prd_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "prd_review")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("prd_review", ctx)

    def test_user_prompt_flags_qa(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "qa")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("qa", ctx)

    def test_user_prompt_stays_quiet_in_working_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "working")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            self.assertEqual(data, {})

    def test_pre_compact_preserves_task_state_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "plan_review")

            text = run_event(root, "PreCompact").stdout
            self.assertIn("[DevFlow State", text)
            self.assertIn("Phase: plan_review", text)
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

    def test_session_start_uses_payload_cwd_not_process_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "task"
            other = Path(temp_dir) / "other"
            root.mkdir()
            other.mkdir()
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "working")

            result = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(root),
                    }
                ),
                text=True,
                capture_output=True,
                cwd=other,
                check=True,
            )
            ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("phase: working", ctx)
            self.assertIn("type: feature", ctx)


class NewestPluginDirTest(unittest.TestCase):
    def test_prefers_higher_version_over_older_mtime(self):
        hook = _load_hook_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            older = Path(temp_dir) / "0.9.0"
            newer = Path(temp_dir) / "2.0.0"
            older.mkdir()
            newer.mkdir()
            os.utime(older, (2_000_000_000, 2_000_000_000))
            os.utime(newer, (1_000_000_000, 1_000_000_000))
            self.assertEqual(hook._newest_dir([str(older), str(newer)]), str(newer))


if __name__ == "__main__":
    unittest.main()
