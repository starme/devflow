# DevFlow Codex Instructions

You are executing DevFlow in Codex. Read `core/orchestrator/SKILL.md`, `.devflow/project.yaml`, and the current task's `.devflow/task.yaml` before acting. Only old projects fall back to `.devflow/manifest.yaml` (legacy, read-only).

## Commands

- `devflow init`: run the core project analyzer, classify the repository, and write category, capabilities, and evidence to `project.yaml`.
- `devflow start <request>`: begin the v2 lifecycle — anchored Q&A, PRD, plan card, implementation, verification, delivery. The first unfinished task works in-place on a feature branch; a latercomer gets a `.devflow-worktrees/<repo>/<task-id>` worktree.
- `devflow fix <bug>`: run the reduced bugfix lifecycle (diagnosis card, single gate).
- `devflow status`: report category, capability, phase, artifacts, and next action.
- `devflow next`: resume the selected task; after a merged PR this is the path into done cleanup.

## Codex safety capability

This adapter is **soft**. Do not claim Claude Code-style hard `PreToolUse` interception. Apply `.devflow/redlines.yaml` as instructions, use Codex command approval requests where the host exposes them, and invoke the core audit logger after actions. Do not read `.env*`, credentials, secrets, or private key files.

## Delivery (soft)

Delivery lifecycle is **soft** under Codex. `git commit` / `git push` are executed through the host approval mechanism (not claimed as a Codex hard capability). PR creation is delegated via `router` mode: the host reports back the PR URL under `gh_pr_url`, which is written to `.devflow/pr.md`. Codex does **not** fabricate a hard PR-creation capability, and the PR is never merged automatically. After delivery closes, local cleanup (`git worktree remove`, `git branch -d`, `git checkout <base_ref>`) may run; the remote branch is never deleted.

## Verification (GATE-V)

Codex has no subagent mechanism, so the independent `devflow-verifier` dispatch does not apply. The Codex main thread executes the plan card's acceptance criteria itself and marks the verification report **"main-thread verification, not an independent verifier"**. Never report a live app-server check as PASS when it is unavailable — mark it BLOCKED.

## Context and boundaries

Task state lives in `.devflow/task.yaml` (`task.current_phase`: `qa → prd_review → plan_review → working → deliver_confirm → done`). There is no runtime `context.json` in v2. Process artifacts (PRD, plan card, verification report) are published only in delivery to `.devflow/tasks/<task-id>/`.
