#!/usr/bin/env python3
"""Authoritative project-root resolution, shared by hooks and orchestrator.

DevFlow's single rule for where state lives:

    The project root is the directory the session starts in, and only that
    directory.  A directory owns a DevFlow project when it contains a
    ``.devflow/`` tree; there is no upward search at run time.

Why no upward search: a workspace aggregates independent repositories, and a
repository may hold its own (inherited-then-customised) ``.devflow``.  Walking
up would let a parent's ``.devflow`` — or an unrelated neighbour's — capture a
session that belongs to the child.  Root identity is therefore decided once, at
initialisation time, and recorded by the ``.devflow/`` that init wrote.

Consequences that fall out of the rule:

* A child repository started without its own ``.devflow`` is *uninitialised*,
  even when an ancestor workspace exists.  The caller asks the user to
  initialise; it never silently adopts the ancestor's state.
* The launch directory is authoritative.  When it has no ``.devflow/`` the
  session is uninitialised, even if a drifted ``cwd`` sits inside a child that
  has one — no other directory may stand in for the launch directory.
* The workspace/multi-repo capability belongs to the directory whose
  ``.devflow`` declares ``workspaces:`` — starting anywhere else operates on
  that directory alone.
* Git is optional.  Root identity does not depend on version control at all.

The module is standard-library only and free of import-time couplings, so the
zero-dependency hooks (``python3 -B -S``) and the orchestrator can both import
it.
"""

from __future__ import annotations

import os
from pathlib import Path


def _normalize(cwd: object) -> Path | None:
    """Resolve a candidate directory, never substituting a background default.

    ``None``/empty means "no candidate supplied" — it must NOT silently become
    ``Path.cwd()``, or a hook process started in the plugin checkout would make
    an uninitialised session look initialised with the wrong project's state.
    """
    if cwd is None or cwd == "":
        return None
    try:
        return Path(cwd).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def session_launch_dir(payload_cwd: object = None) -> Path | None:
    """Return the ONE directory that is the session's root candidate.

    ``CLAUDE_PROJECT_DIR`` (fixed at session start, exported to hook processes)
    wins.  When it is absent — a host that does not set it — the hook payload
    ``cwd`` is used.  The process working directory is consulted ONLY when both
    are missing, because Claude Code does not guarantee a hook process starts
    in the launch directory.

    There is deliberately no list of fallbacks to try in turn: the launch
    directory is authoritative.  If it has no ``.devflow/``, the session is
    uninitialised — no child, parent, or neighbour's ``.devflow`` may stand in.
    """
    return (
        _normalize(os.environ.get("CLAUDE_PROJECT_DIR"))
        or _normalize(payload_cwd)
        or _normalize(Path.cwd())
    )


def resolve_project_root(cwd: object = None) -> Path | None:
    """Return the directory that owns DevFlow state for *cwd*, or ``None``.

    *cwd* is a concrete directory (the launch directory, a tool's working
    directory, or a repository root).  Returns *cwd* itself when it contains
    ``.devflow/``; otherwise ``None``, signalling an uninitialised directory.
    No ancestor is ever consulted.
    """
    start = _normalize(cwd)
    if start is None:
        return None
    if (start / ".devflow").is_dir():
        return start
    return None


def resolve_session_project_root(payload_cwd: object = None) -> Path | None:
    """Return the session's project root, or ``None`` when uninitialised.

    Resolves the single authoritative launch directory (see
    :func:`session_launch_dir`) and checks whether it owns ``.devflow/``.  A
    launch directory without one means "uninitialised", even if the drifting
    payload ``cwd`` happens to sit inside a child directory that has its own
    ``.devflow`` — the caller must offer init, not silently adopt that child.
    """
    launch = session_launch_dir(payload_cwd)
    if launch is None:
        return None
    return resolve_project_root(launch)
