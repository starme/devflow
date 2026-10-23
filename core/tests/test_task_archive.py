"""Tests for archiving task state before it is overwritten.

In-place tasks all share ``repo_root/.devflow/task.yaml``. Starting the next
task used to erase the previous one's id/branch/parent chain, so plan A
snapshots it first and plan D lets the done-cleanup re-create a missing
snapshot. Both paths funnel through ``archive_task_state``.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parent.parent / "orchestrator"
sys.path.insert(0, str(ORCH_DIR))

from task_state import (  # noqa: E402
    TaskRecord,
    archive_task_state,
    load_task,
    render_task_yaml,
)


def _record(task_id="task-abc123", **overrides):
    kwargs = {
        "task_id": task_id,
        "slug": "task",
        "kind": "chore",
        "description": "previous task",
        "base_ref": "main",
        "base_commit": "abc123",
        "branch": f"chore/{task_id}",
        "worktree": "/tmp/repo",
    }
    kwargs.update(overrides)
    return TaskRecord(**kwargs)


class ArchiveTaskStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.devflow = Path(self._tmp.name) / ".devflow"
        self.devflow.mkdir()
        self.task_file = self.devflow / "task.yaml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshots_existing_state_into_task_directory(self):
        record = _record()
        self.task_file.write_text(render_task_yaml(record), encoding="utf-8")

        archive = archive_task_state(self.task_file)

        self.assertEqual(archive, self.devflow / "tasks" / record.task_id / "task.yaml")
        self.assertEqual(load_task(archive), record)

    def test_existing_archive_is_never_overwritten(self):
        # A published archive is the delivery record; a later re-run of the
        # same task id must not replace it with a scratch copy.
        record = _record()
        self.task_file.write_text(render_task_yaml(record), encoding="utf-8")
        published = self.devflow / "tasks" / record.task_id / "task.yaml"
        published.parent.mkdir(parents=True)
        published.write_text("published: true\n", encoding="utf-8")

        self.assertIsNone(archive_task_state(self.task_file))
        self.assertEqual(published.read_text(encoding="utf-8"), "published: true\n")

    def test_missing_task_file_is_a_no_op(self):
        self.assertIsNone(archive_task_state(self.task_file))
        self.assertFalse((self.devflow / "tasks").exists())

    def test_malformed_state_is_skipped_without_partial_copy(self):
        self.task_file.write_text('schema_version: 2\ntask:\n  id: "broken"\n', encoding="utf-8")

        self.assertIsNone(archive_task_state(self.task_file))
        self.assertFalse((self.devflow / "tasks").exists())

    def test_missing_task_id_is_skipped(self):
        self.task_file.write_text("", encoding="utf-8")
        self.assertIsNone(archive_task_state(self.task_file))

    def test_ids_that_could_escape_the_tasks_directory_are_rejected(self):
        for unsafe in ("../escape", "a/b", ".."):
            with self.subTest(task_id=unsafe):
                path = Path(self._tmp.name) / "unsafe"
                path.mkdir(exist_ok=True)
                target = path / "task.yaml"
                target.write_text(
                    render_task_yaml(_record(task_id=unsafe)),
                    encoding="utf-8",
                )
                self.assertIsNone(archive_task_state(target))
                self.assertFalse((path / "tasks").exists())


if __name__ == "__main__":
    unittest.main()
