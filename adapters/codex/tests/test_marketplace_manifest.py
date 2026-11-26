import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN = ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
SKILL = ROOT / "plugins" / "devflow" / "skills" / "devflow" / "SKILL.md"

# Semver, matching the manifest convention (MAJOR.MINOR.PATCH).
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def test_repository_marketplace_manifest_points_to_repo_root():
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert marketplace["name"] == "devflow-marketplace"
    plugin = marketplace["plugins"][0]
    assert plugin["name"] == "devflow"
    assert plugin["source"]["path"] == "."


def test_plugin_manifest_exposes_devflow_skill():
    plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert plugin["name"] == "devflow"
    # Assert the format, not a literal: pinning the number made every
    # release fail this test for no defect.
    assert re.search(_VERSION, plugin["version"])
    assert plugin["author"]["name"] == "starme"
    assert plugin["skills"] == "./plugins/devflow/skills/"
    assert SKILL.is_file()


def test_claude_and_codex_manifests_share_version():
    # Both manifests ship the same plugin, so a release must bump both or
    # the marketplace serves two versions of one name.
    codex = json.loads(PLUGIN.read_text(encoding="utf-8"))
    claude = json.loads(CLAUDE_PLUGIN.read_text(encoding="utf-8"))
    assert codex["version"] == claude["version"]


def test_marketplace_source_includes_core_and_codex_manifest():
    source = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]["source"]["path"]
    plugin_root = (ROOT / source).resolve()
    assert plugin_root == ROOT.resolve()
    assert (plugin_root / ".codex-plugin" / "plugin.json").is_file()
    assert (plugin_root / "core" / "orchestrator").is_dir()
    assert (plugin_root / "core" / "orchestrator" / "delivery.py").is_file()
    assert (plugin_root / "core" / "orchestrator" / "artifact_publish.py").is_file()

