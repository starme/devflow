"""Regression tests for the audit-log hook after the context.json retirement.

v2 (ADR-0005) removed the runtime ``context.json``. The audit log's run id
must now come from ``task.yaml`` — the failure mode this guards against is the
logger going silently dead while every other test still passes.
"""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


def _load_hook():
    spec = importlib.util.spec_from_file_location("audit_log_hook", HOOKS_DIR / "audit-log.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".devflow").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_task(self, task_id="task-abc", phase="working"):
        (self.root / ".devflow" / "task.yaml").write_text(
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

    def _run_hook(self, command="echo hello"):
        hook = _load_hook()
        payload = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.root),
            }
        )
        with (
            mock.patch.object(sys, "argv", ["audit-log.py"]),
            mock.patch("sys.stdin", io.StringIO(payload)),
            self.assertRaises(SystemExit),
        ):
            hook.main()

    def _log_path(self, run_id):
        return self.root / ".devflow" / "runs" / run_id / "audit.log"

    def test_run_id_derived_from_task_id(self):
        hook = _load_hook()
        self._write_task()
        context = hook.load_context(self.root)
        self.assertEqual(context["run_id"], "task-abc")
        self.assertEqual(context["current_phase"], "working")

    def test_no_task_means_no_run_id(self):
        hook = _load_hook()
        context = hook.load_context(self.root)
        self.assertNotIn("run_id", context)

    def test_active_task_writes_audit_line(self):
        self._write_task()
        self._run_hook()
        log = self._log_path("task-abc")
        self.assertTrue(log.is_file(), "audit log was not written")
        self.assertIn("echo hello", log.read_text(encoding="utf-8"))

    def test_done_task_writes_nothing(self):
        self._write_task(phase="done")
        self._run_hook()
        self.assertFalse(self._log_path("task-abc").exists())

    def test_missing_task_writes_nothing(self):
        self._run_hook()
        self.assertFalse((self.root / ".devflow" / "runs").exists())


if __name__ == "__main__":
    unittest.main()
