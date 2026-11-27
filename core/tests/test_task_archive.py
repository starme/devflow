"""Tests for archiving task state before it is overwritten.

In-place tasks all share ``repo_root/.devflow/task.yaml``. Starting the next
task used to erase the previous one's id/branch/parent chain, so plan A
snapshots it first and plan D lets the done-cleanup re-create a missing
snapshot. Both paths funnel through ``archive_task_state``.
"""

import sys
import tempfile
from pathlib import Path

import pytest

ORCH_DIR = Path(__file__).resolve().parent.parent / "orchestrator"
sys.path.insert(0, str(ORCH_DIR))

from task_state import (
    TaskRecord,
    archive_task_state,
    load_task,
    render_task_yaml,
)


@pytest.fixture(autouse=True)
def st():
    from types import SimpleNamespace
    st = SimpleNamespace()
    st._tmp = tempfile.TemporaryDirectory()
    st.devflow = Path(st._tmp.name) / ".devflow"
    st.devflow.mkdir()
    st.task_file = st.devflow / "task.yaml"
    yield st
    st._tmp.cleanup()


def _record(task_id="task-abc123", **overrides):
    kwargs = {
        "task_id": task_id,
        "slug": "task",
        "kind": "chore",
        "description": "previous task",
        "base_ref": "main",
        "base_commit": "abc123",
        "branch": f"chore/{task_id}",
        "working_dir": "/tmp/repo",
    }
    kwargs.update(overrides)
    return TaskRecord(**kwargs)


def test_snapshots_existing_state_into_task_directory(st):
    record = _record()
    st.task_file.write_text(render_task_yaml(record), encoding="utf-8")

    archive = archive_task_state(st.task_file)

    assert archive == st.devflow / "tasks" / record.task_id / "task.yaml"
    assert load_task(archive) == record


def test_existing_archive_is_never_overwritten(st):
    # A published archive is the delivery record; a later re-run of the
    # same task id must not replace it with a scratch copy.
    record = _record()
    st.task_file.write_text(render_task_yaml(record), encoding="utf-8")
    published = st.devflow / "tasks" / record.task_id / "task.yaml"
    published.parent.mkdir(parents=True)
    published.write_text("published: true\n", encoding="utf-8")

    assert archive_task_state(st.task_file) is None
    assert published.read_text(encoding="utf-8") == "published: true\n"


def test_missing_task_file_is_a_no_op(st):
    assert archive_task_state(st.task_file) is None
    assert not ((st.devflow / "tasks").exists())


def test_malformed_state_is_skipped_without_partial_copy(st):
    st.task_file.write_text('schema_version: 2\ntask:\n  id: "broken"\n', encoding="utf-8")

    assert archive_task_state(st.task_file) is None
    assert not ((st.devflow / "tasks").exists())


def test_missing_task_id_is_skipped(st):
    st.task_file.write_text("", encoding="utf-8")
    assert archive_task_state(st.task_file) is None


@pytest.mark.parametrize("unsafe", ("../escape", "a/b", ".."))
def test_ids_that_could_escape_the_tasks_directory_are_rejected(unsafe, st):
    path = Path(st._tmp.name) / "unsafe"
    path.mkdir(exist_ok=True)
    target = path / "task.yaml"
    target.write_text(
        render_task_yaml(_record(task_id=unsafe)),
        encoding="utf-8",
    )
    assert archive_task_state(target) is None
    assert not ((path / "tasks").exists())

