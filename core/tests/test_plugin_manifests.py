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


def subtest(**_kwargs):
    """Migration stand-in for unittest subTest: a no-op context manager."""
    from contextlib import nullcontext
    return nullcontext()

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


def test_all_plugin_manifests_exist():
    for label, path in PLUGIN_MANIFESTS.items():
        with subtest(manifest=label):
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


def test_skill_directories_resolve():
    # Root manifests are published from the repo root; the nested fallback
    # is published from its own package directory.
    package_roots = {
        "claude": ROOT,
        "codex-root": ROOT,
        "codex-nested": ROOT / "plugins" / "devflow",
    }
    for label, path in PLUGIN_MANIFESTS.items():
        with subtest(manifest=label):
            skills = _load(path).get("skills")
            if not skills:
                continue
            assert (package_roots[label] / skills).is_dir(), f"{label}: skills path {skills!r} does not resolve"


def test_marketplaces_share_a_name():
    names = {label: _load(p)["name"] for label, p in MARKETPLACES.items()}
    assert set(names.values()) == {"devflow-marketplace"}


def test_marketplaces_expose_the_devflow_plugin():
    for label, path in MARKETPLACES.items():
        with subtest(marketplace=label):
            plugins = _load(path)["plugins"]
            assert [p["name"] for p in plugins] == ["devflow"]


def test_readme_version_matches_the_manifests():
    version = _load(PLUGIN_MANIFESTS["claude"])["version"]
    for name in ("README.md", "README.zh-CN.md"):
        with subtest(readme=name):
            text = (ROOT / name).read_text(encoding="utf-8")
            assert version in text.split("\n\n")[1], f"{name} does not state version {version} in its header"

