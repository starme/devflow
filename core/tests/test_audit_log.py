"""Regression tests for the audit-log hook after the context.json retirement.

v2 (ADR-0005) removed the runtime ``context.json``. The audit log's run id
must now come from ``task.yaml`` — the failure mode this guards against is the
logger going silently dead while every other test still passes.
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def st():
    from types import SimpleNamespace
    st = SimpleNamespace()
    st._tmp = tempfile.TemporaryDirectory()
    st.root = Path(st._tmp.name)
    (st.root / ".devflow").mkdir()
    yield st
    st._tmp.cleanup()


HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


def _load_hook():
    spec = importlib.util.spec_from_file_location("audit_log_hook", HOOKS_DIR / "audit-log.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_task(st, task_id="task-abc", phase="working"):
    (st.root / ".devflow" / "task.yaml").write_text(
        "schema_version: 2\n"
        "task:\n"
        f'  id: "{task_id}"\n'
        '  slug: "test"\n'
        '  kind: "chore"\n'
        '  description: "test"\n'
        f'  current_phase: "{phase}"\n'
        '  status: "active"\n',
        encoding="utf-8",
    )


def _run_hook(st, command="echo hello"):
    hook = _load_hook()
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(st.root),
        }
    )
    with (
        mock.patch.object(sys, "argv", ["audit-log.py"]),
        mock.patch("sys.stdin", io.StringIO(payload)),
        mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(st.root)}),
        pytest.raises(SystemExit),
    ):
        hook.main()


def _log_path(st, run_id):
    return st.root / ".devflow" / "runs" / run_id / "audit.log"


def test_run_id_derived_from_task_id(st):
    hook = _load_hook()
    _write_task(st)
    context = hook.load_context(st.root)
    assert context["run_id"] == "task-abc"
    assert context["current_phase"] == "working"


def test_no_task_means_no_run_id(st):
    hook = _load_hook()
    context = hook.load_context(st.root)
    assert "run_id" not in context


def test_active_task_writes_audit_line(st):
    _write_task(st)
    _run_hook(st)
    log = _log_path(st, "task-abc")
    assert log.is_file(), "audit log was not written"
    assert "echo hello" in log.read_text(encoding="utf-8")


def test_done_task_writes_nothing(st):
    _write_task(st, phase="done")
    _run_hook(st)
    assert not (_log_path(st, "task-abc").exists())


def test_missing_task_writes_nothing(st):
    _run_hook(st)
    assert not ((st.root / ".devflow" / "runs").exists())

