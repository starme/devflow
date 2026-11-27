"""Cross-manifest consistency tests.

DevFlow ships three plugin manifests for two hosts:

- ``.claude-plugin/plugin.json``      — Claude Code
- ``.codex-plugin/plugin.json``       — Codex (marketplace source)
- ``plugins/devflow/.codex-plugin/plugin.json`` — nested Skill-only fallback

They are maintained by hand, so a version bump applied to one and forgotten in
the others ships a broken release. That already happened once (PR #14, where a
marketplace test still asserted 1.0.1 while the main manifest had moved on).
These tests pin the fields that must agree.

``skills`` legitimately differs between the root manifests and the nested
fallback (relative to each package root), so only existence is asserted.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PLUGIN_MANIFESTS = {
    "claude": ROOT / ".claude-plugin" / "plugin.json",
    "codex-root": ROOT / ".codex-plugin" / "plugin.json",
    "codex-nested": ROOT / "plugins" / "devflow" / ".codex-plugin" / "plugin.json",
}

MARKETPLACES = {
    "claude": ROOT / ".claude-plugin" / "marketplace.json",
    "codex": ROOT / ".agents" / "plugins" / "marketplace.json",
}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label,path", PLUGIN_MANIFESTS.items())
def test_all_plugin_manifests_exist(label, path):
    assert path.is_file(), f"{label} manifest missing: {path}"


def test_plugin_names_agree():
    names = {label: _load(p)["name"] for label, p in PLUGIN_MANIFESTS.items()}
    assert set(names.values()) == {"devflow"}


def test_plugin_versions_agree():
    versions = {label: _load(p)["version"] for label, p in PLUGIN_MANIFESTS.items()}
    # pyproject carries the same release version; a bump must touch it too.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', text, flags=re.MULTILINE)
    assert m is not None, "pyproject.toml has no parseable project version"
    versions["pyproject"] = m.group(1)
    assert len(set(versions.values())) == 1, f"plugin versions drifted apart: {versions}"


@pytest.mark.parametrize("label,path", PLUGIN_MANIFESTS.items())
def test_skill_directories_resolve(label, path):
    # Root manifests are published from the repo root; the nested fallback
    # is published from its own package directory.
    package_roots = {
        "claude": ROOT,
        "codex-root": ROOT,
        "codex-nested": ROOT / "plugins" / "devflow",
    }
    skills = _load(path).get("skills")
    if not skills:
        return  # nothing declared to resolve (main used `continue`)
    assert (package_roots[label] / skills).is_dir(), f"{label}: skills path {skills!r} does not resolve"


def test_marketplaces_share_a_name():
    names = {label: _load(p)["name"] for label, p in MARKETPLACES.items()}
    assert set(names.values()) == {"devflow-marketplace"}


@pytest.mark.parametrize("label,path", MARKETPLACES.items())
def test_marketplaces_expose_the_devflow_plugin(label, path):
    plugins = _load(path)["plugins"]
    assert [p["name"] for p in plugins] == ["devflow"]


@pytest.mark.parametrize("name", ("README.md", "README.zh-CN.md"))
def test_readme_version_matches_the_manifests(name):
    version = _load(PLUGIN_MANIFESTS["claude"])["version"]
    text = (ROOT / name).read_text(encoding="utf-8")
    assert version in text.split("\n\n")[1], f"{name} does not state version {version} in its header"

