---
name: devflow
description: Adaptive DevFlow lifecycle orchestration for applications, AI agents, Agent Plugins, Skills, and MCP servers.
---

# DevFlow for Codex

Read the repository's `.devflow/project.yaml` and the current task's `.devflow/task.yaml`/`.devflow/context.json` before acting. If only `.devflow/manifest.yaml` exists, perform the idempotent legacy metadata migration during `init`/`next` (not in a lifecycle hook): create `project.yaml`, `tasks/legacy/task.yaml`, and `migration.yaml` without modifying or deleting the manifest.

Default isolation is in-place: the first unfinished task works on a feature branch in the main workspace. Only a latercomer that would collide with that unfinished task gets a `.devflow-worktrees/<repo>/<task-id>` worktree. Pin `cwd` to the task workspace. Process artifacts are published only in DELIVERY to `.devflow/tasks/<task-id>/`.

Core scripts (`delivery.py`, `artifact_publish.py`, `worktree_manager.py`) live at `$DEVFLOW_CORE_ROOT` or `<plugin-root>/core/orchestrator/`. This marketplace package is the repository root so those scripts are installed with the skill.

## Commands

- `$devflow init`: analyze safe repository evidence and record category, capabilities, evidence, and selected tracks.
- `$devflow start <request>`: start a feature lifecycle.
- `$devflow fix <bug>`: run the reduced bugfix lifecycle.
- `$devflow status`: report project configuration plus task/worktree status; use `--all` to list all tasks.
- `$devflow next`: resume the selected task; use `--task <task-id>` when multiple tasks exist.

## Safety

Codex integration is **soft**. Use Codex command approvals and the project's redline instructions. Do not claim generic Claude Code `PreToolUse` file-write denial. Do not read `.env*`, credentials, secrets, or private keys. Update `.devflow/context.json` at phase and dispatch boundaries and append audit records after actions when the host supports the bridge.

## Track selection

Use `project.category`, `project.capabilities`, and `workflow.tracks`. Do not dispatch empty backend/frontend work for Agent Plugin, Skill, MCP, or AI Agent projects. Use plugin, command, skill, agent, prompt, hook, tool, integration, evaluation, packaging, and documentation tracks as selected by the manifest.
