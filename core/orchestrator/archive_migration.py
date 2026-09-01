#!/usr/bin/env python3
"""One-shot migration of legacy scattered deliverables into ``.devflow/tasks/``.

DevFlow previously left some deliverables flattened at the project root (or in
``docs/``) instead of inside the per-task archive namespace.  This module moves
them into semantic ``legacy-*`` directories under ``.devflow/tasks/`` so the
archive tracks exactly one shape.  It is idempotent: a target that already
exists with identical content is skipped; a differing target raises a conflict
(never last-writer-wins).  Originals are never deleted — for the legacy PRD,
the original position is overwritten with a one-line pointer; for the flat
deliverables, ``shutil.copy2`` leaves the source in place.
"""
from __future__ import annotations

import shutil
from pathlib import Path


class ArchiveMigrationConflict(RuntimeError):
    """Raised when a migration target exists with different content."""


# Flat deliverables mapped to a semantic legacy-* directory.  ``short_name`` is
# the deterministic filename inside that directory; no task id is fabricated
# because none of these artifacts ever belonged to a real task (PRD decision 4).
_FLAT_MIGRATIONS = (
    ("PRD-DevFlow.md", "legacy-v01-prd", "PRD-DevFlow.md"),
    ("review-report.md", "legacy-doc-review", "review-report.md"),
    ("docs/architecture.md", "legacy-v02-arch", "architecture.md"),
    ("docs/delivery-report.md", "legacy-v02-delivery", "delivery-report.md"),
)

# The legacy PRD is a special case: it is *moved* (copy + pointer file at the
# original location) and its manifest references are re-pointed.
_LEGACY_PRD_SOURCE = ".devflow/agent-plugin-compatibility-prd.md"
_LEGACY_PRD_TARGET = ".devflow/tasks/legacy/prd-agent-plugin-compatibility.md"


def resolve_target_dir(root: Path, semantic_dir: str) -> Path:
    """Return the archive target directory for *semantic_dir*."""
    return root / ".devflow" / "tasks" / semantic_dir


def _copy_if_unchanged(source: Path, target: Path) -> bool:
    """Copy *source* to *target*, returning True when a file was created.

    A target that already exists with identical content is skipped (returns
    False); one with different content raises so a prior archive is never
    silently clobbered.
    """
    if target.exists():
        if _same_content(source, target):
            return False
        raise ArchiveMigrationConflict(
            f"archive migration target differs: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _same_content(source: Path, target: Path) -> bool:
    return source.read_bytes() == target.read_bytes()


def _write_if_absent(path: Path, content: str) -> bool:
    """Write *content* to *path* unless the file already holds it (idempotent)."""
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ArchiveMigrationConflict(f"migration target differs: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _write_pointer(path: Path, pointer: str) -> bool:
    """Overwrite *path* with the one-line pointer (idempotent).

    Unlike ``_write_if_absent``, replacing the original body is the intended
    "move with pointer" semantics, so differing content is overwritten rather
    than refused; a second run finds the pointer already in place and skips.
    """
    if path.exists() and path.read_text(encoding="utf-8") == pointer:
        return False
    path.write_text(pointer, encoding="utf-8")
    return True


def _readme_for(source_rel: str, semantic_dir: str) -> str:
    """Render a minimal source index for a legacy-* directory."""
    return (
        "# Legacy Artifacts\n"
        "\n"
        f"source: \"{source_rel}\"\n"
        f"directory: \"{semantic_dir}\"\n"
        "migrated: true\n"
    )


def _pointer_for(target_rel: str) -> str:
    """Render the one-line markdown pointer left at a moved PRD's original spot."""
    return f"Moved to [{target_rel}]({target_rel})\n"


# ---------------------------------------------------------------------------
# Manifest rewrite
# ---------------------------------------------------------------------------

def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _render_scalar(indent: int, key: str, value: str) -> str:
    return f"{' ' * indent}{key}: \"{value}\""


def replace_nested_scalar(
    content: str, section_path: tuple[str, ...], key: str, new_value: str
) -> str:
    """Replace the scalar ``key`` under *section_path* in *content*.

    Walks lines by indentation to locate exactly the targeted key (so
    ``phases.prd_writing.prd_path`` does not collide with ``artifacts.prd``).
    Returns the rewritten text, preserving all comments and other fields.
    """
    lines = content.split("\n")
    stack: list[tuple[int, str]] = []  # (indent, section name)
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        indent = _indent_of(line)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stripped.endswith(":"):
            # A mapping/list section header (value after the colon is empty).
            stack.append((indent, stripped[:-1]))
            out.append(line)
            continue
        name = stripped.split(":", 1)[0].strip()
        path = tuple(n for _, n in stack)
        if not replaced and path == section_path and name == key:
            out.append(_render_scalar(indent, key, new_value))
            replaced = True
            continue
        out.append(line)
    return "\n".join(out)


def update_manifest(root: Path) -> bool:
    """Re-point manifest references to migrated paths (idempotent)."""
    manifest = root / ".devflow" / "manifest.yaml"
    if not manifest.is_file():
        return False
    content = manifest.read_text(encoding="utf-8")
    updated = False
    new_prd = ".devflow/tasks/legacy/prd-agent-plugin-compatibility.md"
    prd_rewritten = replace_nested_scalar(
        content, ("phases", "prd_writing"), "prd_path", new_prd
    )
    if prd_rewritten != content:
        content = prd_rewritten
        updated = True
    artifacts_rewritten = replace_nested_scalar(content, ("artifacts",), "prd", new_prd)
    if artifacts_rewritten != content:
        content = artifacts_rewritten
        updated = True
    arch_new = ".devflow/tasks/legacy-v02-arch/architecture.md"
    arch_rewritten = replace_nested_scalar(
        content, ("phases", "architecture"), "architecture_doc_path", arch_new
    )
    if arch_rewritten != content:
        content = arch_rewritten
        updated = True
    if updated:
        manifest.write_text(content, encoding="utf-8")
    return updated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def migrate_legacy_archive(root: Path) -> dict[str, object]:
    """Migrate legacy deliverables into ``.devflow/tasks/`` and sync manifest.

    Returns ``{"status", "created", "skipped"}`` where status is ``migrated``
    (something changed), ``already_migrated`` (everything already in place), or
    ``not_applicable`` (no legacy sources and no manifest to sync).
    """
    root = root.resolve()
    created: list[str] = []
    skipped: list[str] = []

    # 1. Legacy PRD: copy + pointer + (manifest sync handled below).  The
    # source becomes a pointer after the first run, so a re-run detects the
    # pointer and skips the copy rather than comparing pointer-vs-body.
    prd_src = root / _LEGACY_PRD_SOURCE
    prd_dst = root / _LEGACY_PRD_TARGET
    pointer = _pointer_for(_LEGACY_PRD_TARGET)
    if prd_src.is_file():
        if prd_src.read_text(encoding="utf-8") == pointer:
            skipped.append(_LEGACY_PRD_TARGET)
        else:
            if _copy_if_unchanged(prd_src, prd_dst):
                created.append(_LEGACY_PRD_TARGET)
            else:
                skipped.append(_LEGACY_PRD_TARGET)
            if _write_pointer(prd_src, pointer):
                created.append(_LEGACY_PRD_SOURCE)

    # 2. Flat deliverables into semantic legacy-* directories.
    for source_rel, semantic_dir, short_name in _FLAT_MIGRATIONS:
        source = root / source_rel
        if not source.is_file():
            continue
        target_dir = resolve_target_dir(root, semantic_dir)
        target = target_dir / short_name
        target_rel = f".devflow/tasks/{semantic_dir}/{short_name}"
        if _copy_if_unchanged(source, target):
            created.append(target_rel)
        else:
            skipped.append(target_rel)
        if _write_if_absent(target_dir / "README.md", _readme_for(source_rel, semantic_dir)):
            created.append(f".devflow/tasks/{semantic_dir}/README.md")

    # 3. Manifest reference re-pointing (legacy PRD + architecture_doc_path).
    if update_manifest(root):
        created.append(".devflow/manifest.yaml")

    if created:
        return {"status": "migrated", "created": created, "skipped": skipped}
    if skipped:
        return {"status": "already_migrated", "created": created, "skipped": skipped}
    return {"status": "not_applicable", "created": [], "skipped": []}


if __name__ == "__main__":
    import json
    import sys

    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    result = migrate_legacy_archive(project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))