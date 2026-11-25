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


def run_event(root: Path, event: str, project_dir=None, **extra) -> subprocess.CompletedProcess:
    payload = {
        "hook_event_name": event,
        "cwd": str(root),
        **extra,
    }
    env = dict(os.environ)
    # Claude Code exports the fixed session launch dir; simulate it so tests
    # exercise the same signal production uses.
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir is not None else root)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=root,
        env=env,
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

    def test_user_prompt_maps_retired_prd_review_onto_plan_review(self) -> None:
        """ADR-0006 D1 retired ``prd_review``. A task.yaml written before the
        change still carries it, so the notice must land on the merged gate
        rather than go silent."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            self.write_task_yaml(devflow, "prd_review")

            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("plan_review", ctx)
            self.assertIn("Awaiting", ctx)

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


class QaRecallPromptTest(unittest.TestCase):
    """The 2026-11 dogfood skipped design-time recall entirely: SKILL says to
    do it in qa, but nothing reminded the model, so it only happened when the
    implementer thought of it. A hook notice is the difference between a rule
    and a hope."""

    def test_qa_phase_prompts_for_recall(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "task.yaml").write_text(
                "schema_version: 2\n"
                "task:\n"
                '  id: "t-1"\n'
                '  slug: "t"\n'
                '  kind: "feature"\n'
                '  description: "d"\n'
                '  current_phase: "qa"\n'
                '  status: "active"\n',
                encoding="utf-8",
            )
            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("memorant_recall", ctx)
        self.assertIn("历史经验", ctx)

    def test_other_gate_phases_keep_the_plain_notice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devflow = root / ".devflow"
            devflow.mkdir()
            (devflow / "task.yaml").write_text(
                "schema_version: 2\n"
                "task:\n"
                '  id: "t-1"\n'
                '  slug: "t"\n'
                '  kind: "feature"\n'
                '  description: "d"\n'
                '  current_phase: "plan_review"\n'
                '  status: "active"\n',
                encoding="utf-8",
            )
            data = json.loads(run_event(root, "UserPromptSubmit").stdout)
            ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Awaiting", ctx)
        self.assertNotIn("memorant_recall", ctx)


class NaturalLanguageEntryTest(unittest.TestCase):
    """ADR-0006 D4: a keyword prefilter decides whether the model is even asked.

    The prefilter is deliberately coarse; these cases pin that it fires on
    development requests, stays quiet on ordinary conversation, and never
    hijacks an explicit slash command.
    """

    @classmethod
    def setUpClass(cls):
        cls.hook = _load_hook_module()

    def test_development_requests_are_candidates(self):
        for prompt in (
            "分析需求进行开发",
            "把这个 bug 修了",
            "帮我实现一个导出功能",
            "这个接口报错了",
            "refactor the auth module",
            "fix the flaky test",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(self.hook.detect_intent_candidate(prompt), prompt)

    def test_ordinary_conversation_is_not_a_candidate(self):
        for prompt in (
            "今天几号",
            "解释一下这段历史",
            "what does this repo do",
            "",
            "   ",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(self.hook.detect_intent_candidate(prompt), prompt)

    def test_explicit_slash_command_is_never_prefiltered(self):
        """The user already chose a command; guessing on top of it would add
        a confirmation prompt to an intentional action."""
        for prompt in ("/devflow start 做点事", "/plan 重构一下", "/fix bug"):
            with self.subTest(prompt=prompt):
                self.assertFalse(self.hook.detect_intent_candidate(prompt), prompt)

    def test_intent_notice_demands_confirmation_before_starting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = json.loads(
                run_event(root, "UserPromptSubmit", prompt="帮我实现导出功能").stdout
            )
            ctx = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("confirm", ctx)
            self.assertIn("do not start the workflow unprompted", ctx)

    def test_no_notice_when_nothing_looks_like_development(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_event(root, "UserPromptSubmit", prompt="今天天气不错")
            self.assertEqual(result.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
