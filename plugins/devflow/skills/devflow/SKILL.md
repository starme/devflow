---
name: devflow
description: Adaptive DevFlow lifecycle orchestration for applications, AI agents, Agent Plugins, Skills, and MCP servers.
---

# DevFlow for Codex

Read the repository's `.devflow/manifest.yaml` and `.devflow/context.json` before acting. If `.devflow/manifest.yaml` is missing, analyze the repository and initialize it before starting a lifecycle.

## Commands

- `$devflow init`: analyze safe repository evidence and record category, capabilities, evidence, and selected tracks.
- `$devflow start <request>`: start a feature lifecycle.
- `$devflow fix <bug>`: run the reduced bugfix lifecycle.
- `$devflow status`: report category, tracks, phase, artifacts, and next action.
- `$devflow next`: resume the current phase.

## Safety

Codex integration is **soft**. Use Codex command approvals and the project's redline instructions. Do not claim generic Claude Code `PreToolUse` file-write denial. Do not read `.env*`, credentials, secrets, or private keys. Update `.devflow/context.json` at phase and dispatch boundaries and append audit records after actions when the host supports the bridge.

## Track selection

Use `project.category`, `project.capabilities`, and `workflow.tracks`. Do not dispatch empty backend/frontend work for Agent Plugin, Skill, MCP, or AI Agent projects. Use plugin, command, skill, agent, prompt, hook, tool, integration, evaluation, packaging, and documentation tracks as selected by the manifest.
