---
name: devflow
description: Intent-anchoring, verification-gated DevFlow lifecycle for any git repository — anchored Q&A, PRD, plan card, implementation, verification, delivery.
---

# DevFlow for Codex

Read the repository's `.devflow/project.yaml` and the current task's `.devflow/task.yaml` before acting. Only old projects fall back to `.devflow/manifest.yaml` (legacy, read-only — no migration inside a lifecycle hook).

Default isolation is in-place: the first unfinished task works on a feature branch in the main workspace. Only a latercomer that would collide with that unfinished task gets a `.devflow-worktrees/<repo>/<task-id>` worktree. Pin `cwd` to the task workspace. Process artifacts are published only in delivery to `.devflow/tasks/<task-id>/`.

Core scripts (`delivery.py`, `artifact_publish.py`, `worktree_manager.py`) live at `$DEVFLOW_CORE_ROOT` or `<plugin-root>/core/orchestrator/`. This marketplace package is the repository root so those scripts are installed with the skill.

## Commands

- `$devflow init`: analyze safe repository evidence and record category and capabilities in `project.yaml`.
- `$devflow start <request>`: start the feature lifecycle — anchored Q&A (frozen original words, gap-filling questions), PRD, plan card with executable acceptance criteria, implementation, verification, delivery.
- `$devflow fix <bug>`: run the reduced bugfix lifecycle (diagnosis card, single gate).
- `$devflow status`: report project configuration plus task status; use `--all` to list all tasks.
- `$devflow next`: resume the selected task; use `--task <task-id>` when multiple tasks exist.

## Verification (GATE-V)

Codex has no subagent mechanism, so the independent `devflow-verifier` dispatch does not apply: execute the plan card's acceptance criteria in the main thread and mark the verification report **"main-thread verification, not an independent verifier"**.

## Safety

Codex integration is **soft**. Use Codex command approvals and the project's redline instructions. Do not claim generic Claude Code `PreToolUse` file-write denial. Do not read `.env*`, credentials, secrets, or private keys. Append audit records after actions when the host supports the bridge. Delivery is soft: commit/push go through host approval; PR creation is routed via the host (`gh_pr_url`); the PR is never merged automatically.
