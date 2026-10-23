"""Tests for task.yaml rendering.

The renderer is the live writer — ``core/templates/task.yaml`` is a reference
copy. These tests pin the two together so the template cannot drift into
advertising fields the code never writes (the pre-v2 ``title:`` gap).
"""

import re
import sys
import unittest
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parent.parent / "orchestrator"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "task.yaml"
sys.path.insert(0, str(ORCH_DIR))

from task_state import TaskRecord, render_task_yaml  # noqa: E402


def _record(**overrides):
    kwargs = {
        "task_id": "task-abc123",
        "slug": "task",
        "kind": "chore",
        "description": "clean up retired v1 config",
        "base_ref": "main",
        "base_commit": "fba2bb7",
        "branch": "chore/task-abc123",
        "worktree": "/tmp/repo",
    }
    kwargs.update(overrides)
    return TaskRecord(**kwargs)


def _template_task_fields():
    """Top-level ``task:`` child keys declared by the template."""
    content = TEMPLATE.read_text(encoding="utf-8")
    block = content.split("\ntask:\n", 1)[1].split("\n\n", 1)[0]
    return {
        line.strip().split(":", 1)[0]
        for line in block.splitlines()
        if line.startswith("  ") and not line.strip().startswith("#")
    }


def _rendered_task_fields(rendered):
    block = rendered.split("\ntask:\n", 1)[1].split("\n\n", 1)[0]
    return {
        line.strip().split(":", 1)[0]
        for line in block.splitlines()
        if line.startswith("  ") and line.strip()
    }


class RenderTaskYamlTest(unittest.TestCase):
    def test_template_fields_match_renderer_output(self):
        self.assertEqual(
            _template_task_fields(),
            _rendered_task_fields(render_task_yaml(_record())),
        )

    def test_rendered_fields_are_placeholders_only(self):
        # Every field the template advertises must be populated, not a
        # leftover "{{...}}" placeholder.
        self.assertNotIn("{{", render_task_yaml(_record()))

    def test_title_defaults_to_first_description_line(self):
        rendered = render_task_yaml(_record(description="line one\nline two"))
        self.assertIn('  title: "line one"', rendered)

    def test_explicit_title_wins(self):
        rendered = render_task_yaml(_record(title="Explicit Card Title"))
        self.assertIn('  title: "Explicit Card Title"', rendered)

    def test_phase_defaults_to_qa_and_stays_in_six_values(self):
        rendered = render_task_yaml(_record())
        phase = re.search(r'current_phase: "(.*?)"', rendered).group(1)
        self.assertIn(
            phase,
            {"qa", "prd_review", "plan_review", "working", "deliver_confirm", "done"},
        )
        self.assertEqual(phase, "qa")


if __name__ == "__main__":
    unittest.main()
