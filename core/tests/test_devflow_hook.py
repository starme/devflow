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
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "devflow_hook.py"


def subtest(**_kwargs):
    """Migration stand-in for unittest subTest: a no-op context manager."""
    from contextlib import nullcontext
    return nullcontext()

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


_HOOK = _load_hook_module()


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


def test_stop_event_is_noop_even_in_working_phase() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "working")

        output = json.loads(run_event(root, "Stop").stdout)
        assert output == {}


def test_stop_event_is_noop_for_legacy_auto_phase() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        (devflow / "manifest.yaml").write_text(
            "project:\n  current_phase: testing\n", encoding="utf-8"
        )

        output = json.loads(run_event(root, "Stop").stdout)
        assert output == {}


def test_hook_module_has_no_block_emitter() -> None:
    hook = _load_hook_module()
    assert not (hasattr(hook, "emit_stop_block"))
    assert not (hasattr(hook, "handle_stop"))




def test_session_start_reads_kind_and_phase_from_task_yaml() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "working")

        data = json.loads(run_event(root, "SessionStart").stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "type: feature" in ctx
        assert "phase: working" in ctx
        assert "Gates" in ctx


def test_user_prompt_flags_deliver_confirm_gate() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "deliver_confirm")

        data = json.loads(run_event(root, "UserPromptSubmit").stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "deliver_confirm" in ctx
        assert "Awaiting" in ctx


def test_user_prompt_maps_retired_prd_review_onto_plan_review() -> None:
    """ADR-0006 D1 retired ``prd_review``. A task.yaml written before the
    change still carries it, so the notice must land on the merged gate
    rather than go silent."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "prd_review")

        data = json.loads(run_event(root, "UserPromptSubmit").stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "plan_review" in ctx
        assert "Awaiting" in ctx


def test_user_prompt_flags_qa() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "qa")

        data = json.loads(run_event(root, "UserPromptSubmit").stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "qa" in ctx


def test_user_prompt_stays_quiet_in_working_phase() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "working")

        data = json.loads(run_event(root, "UserPromptSubmit").stdout)
        assert data == {}


def test_pre_compact_preserves_task_state_as_text() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "plan_review")

        text = run_event(root, "PreCompact").stdout
        assert "[DevFlow State" in text
        assert "Phase: plan_review" in text
        assert "current_phase:" in text


def test_legacy_manifest_lookup_does_not_migrate() -> None:
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
        assert "phase: testing" in ctx
        assert not ((devflow / "project.yaml").exists())
        assert not ((devflow / "migration.yaml").exists())
        assert not ((devflow / "tasks").exists())


def test_session_start_uses_payload_cwd_not_process_cwd() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "task"
        other = Path(temp_dir) / "other"
        root.mkdir()
        other.mkdir()
        devflow = root / ".devflow"
        devflow.mkdir()
        write_task_yaml(devflow, "working")

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
        assert "phase: working" in ctx
        assert "type: feature" in ctx


def test_prefers_higher_version_over_older_mtime():
    hook = _load_hook_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        older = Path(temp_dir) / "0.9.0"
        newer = Path(temp_dir) / "2.0.0"
        older.mkdir()
        newer.mkdir()
        os.utime(older, (2_000_000_000, 2_000_000_000))
        os.utime(newer, (1_000_000_000, 1_000_000_000))
        assert hook._newest_dir([str(older), str(newer)]) == str(newer)


def test_qa_phase_prompts_for_recall():
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
    assert "memorant_recall" in ctx
    assert "历史经验" in ctx


def test_other_gate_phases_keep_the_plain_notice():
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
    assert "Awaiting" in ctx
    assert "memorant_recall" not in ctx




def test_development_requests_are_candidates():
    for prompt in (
        "分析需求进行开发",
        "把这个 bug 修了",
        "帮我实现一个导出功能",
        "这个接口报错了",
        "refactor the auth module",
        "fix the flaky test",
    ):
        with subtest(prompt=prompt):
            assert _HOOK.detect_intent_candidate(prompt)


def test_ordinary_conversation_is_not_a_candidate():
    for prompt in (
        "今天几号",
        "解释一下这段历史",
        "what does this repo do",
        "",
        "   ",
    ):
        with subtest(prompt=prompt):
            assert not (_HOOK.detect_intent_candidate(prompt))


def test_explicit_slash_command_is_never_prefiltered():
    """The user already chose a command; guessing on top of it would add
    a confirmation prompt to an intentional action."""
    for prompt in ("/devflow start 做点事", "/plan 重构一下", "/fix bug"):
        with subtest(prompt=prompt):
            assert not (_HOOK.detect_intent_candidate(prompt))


def test_intent_notice_demands_confirmation_before_starting():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data = json.loads(
            run_event(root, "UserPromptSubmit", prompt="帮我实现导出功能").stdout
        )
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "confirm" in ctx
        assert "do not start the workflow unprompted" in ctx


def test_no_notice_when_nothing_looks_like_development():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        result = run_event(root, "UserPromptSubmit", prompt="今天天气不错")
        assert result.stdout.strip() == "{}"

