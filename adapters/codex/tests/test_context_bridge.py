import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_bridge import build_core_payload, soft_warning, write_context


class ContextBridgeTest(unittest.TestCase):
    def test_writes_runtime_context_to_task_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_root = root / "task" / ".devflow"
            path = write_context(root, {"task_root": str(task_root), "task_id": "task-a"})
            self.assertEqual(path, task_root.resolve() / "context.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["task_id"], "task-a")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_context(temp_dir, {"current_phase": "testing", "current_agent": "manager"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["current_phase"], "testing")

    def test_builds_core_hook_payload(self):
        payload = json.loads(build_core_payload("Bash", {"command": "pytest"}, "/tmp/project"))
        self.assertEqual(payload["tool_name"], "Bash")
        self.assertEqual(payload["tool_input"]["command"], "pytest")
        self.assertEqual(payload["cwd"], "/private/tmp/project" if sys.platform == "darwin" else "/tmp/project")

    def test_declares_soft_capability_warning(self):
        self.assertIn("soft", soft_warning())
        self.assertIn("pre-tool", soft_warning())


if __name__ == "__main__":
    unittest.main()
