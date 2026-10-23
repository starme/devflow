import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_bridge import build_core_payload, soft_warning


class ContextBridgeTest(unittest.TestCase):
    def test_bridge_has_no_context_writer(self):
        # v2 (ADR-0005): the runtime context.json writer is retired.
        import context_bridge

        self.assertFalse(hasattr(context_bridge, "write_context"))

    def test_builds_core_hook_payload(self):
        payload = json.loads(build_core_payload("Bash", {"command": "pytest"}, "/tmp/project"))
        self.assertEqual(payload["tool_name"], "Bash")
        self.assertEqual(payload["tool_input"]["command"], "pytest")
        self.assertEqual(
            payload["cwd"], "/private/tmp/project" if sys.platform == "darwin" else "/tmp/project"
        )

    def test_declares_soft_capability_warning(self):
        self.assertIn("soft", soft_warning())
        self.assertIn("pre-tool", soft_warning())


if __name__ == "__main__":
    unittest.main()
