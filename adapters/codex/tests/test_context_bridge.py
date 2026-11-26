import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_bridge import build_core_payload, soft_warning


def test_bridge_has_no_context_writer():
    # v2 (ADR-0005): the runtime context.json writer is retired.
    import context_bridge

    assert not (hasattr(context_bridge, "write_context"))


def test_builds_core_hook_payload():
    payload = json.loads(build_core_payload("Bash", {"command": "pytest"}, "/tmp/project"))
    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"]["command"] == "pytest"
    assert payload["cwd"] == "/private/tmp/project" if sys.platform == "darwin" else "/tmp/project"


def test_declares_soft_capability_warning():
    assert "soft" in soft_warning()
    assert "pre-tool" in soft_warning()

