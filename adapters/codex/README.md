# Codex adapter for DevFlow

This directory defines the Codex adapter contract for DevFlow. The portable workflow and safety scripts remain under `../../core/`; this adapter supplies the Codex-native entry points and runtime bridge.

## Status and capability

- Platform: Codex CLI / Codex app-server
- Adapter status: protocol-complete baseline; live app-server execution depends on the installed Codex version and host integration
- Redline capability: **soft**
- Claude Code remains **hard** through its registered `PreToolUse` hook

The soft designation is deliberate. Official Codex documentation currently confirms:

- `turn/start` accepts skill input items;
- MCP tools are first-class extensions;
- MCP tool hooks execute synchronously;
- `item/commandExecution/requestApproval` can ask a client to approve or decline command/network execution.

Those extension points do not establish a generic, synchronous pre-execution deny hook for every file write equivalent to Claude Code `PreToolUse`. The adapter therefore never claims hard file-write interception. It injects the redline policy into Codex instructions, uses Codex approval requests where available, and invokes the core audit logger after actions.

## Files

- `adapter.toml`: machine-readable capability and discovery metadata.
- `AGENTS.md`: project-level Manager instructions for Codex sessions.
- `devflow-codex.md`: Skill/turn payload for the five lifecycle commands.
- `context_bridge.py`: context and core-hook bridge for Codex integrations.
- `install.md`: installation and host integration instructions.
- `tests/test_context_bridge.py`: stdlib-only contract tests.

## Marketplace installation

The recommended user path is the repository's Codex Plugin Marketplace package:

```bash
codex plugin marketplace add starme/devflow --ref main
codex plugin list --marketplace devflow-marketplace
codex plugin add devflow@devflow-marketplace
```

For local development:

```bash
codex plugin marketplace add /absolute/path/to/devflow
codex plugin list --marketplace devflow-marketplace
codex plugin add devflow@devflow-marketplace
```

The package lives under `plugins/devflow/`. The manual Skill-copy procedure in `install.md` is a fallback for older hosts or development experiments.


| DevFlow command | Codex integration |
| --- | --- |
| `devflow init` | Start a turn with the `devflow` skill and run repository analysis. |
| `devflow start <request>` | Start a turn with `$devflow` and the feature request. |
| `devflow fix <bug>` | Start a turn with `$devflow` in bugfix mode. |
| `devflow status` | Read `.devflow/manifest.yaml` and report state. |
| `devflow next` | Resume the phase recorded in `.devflow/manifest.yaml`. |

The adapter does not invent a Codex slash-command API. Hosts may expose the mapping as a shell alias, a Codex Skill, or an app-server `turn/start` request.

## Hook bridge

For a verified Codex command-approval or MCP-hook event, convert the event into the core JSON protocol and invoke the matching script:

```json
{
  "tool_name": "Bash",
  "tool_input": {"command": "..."},
  "cwd": "/absolute/project/path"
}
```

- before an available command approval: ask the Codex client and honor `accept`, `decline`, or `cancel`;
- for file writes without a verified pre-hook: emit the soft warning and continue only under Codex's configured sandbox/approval policy;
- after successful actions: invoke `../../core/hooks/audit-log.py`.

Never convert soft mode into a fake `permissionDecision: deny`. Core redline behavior remains the baseline when a host can provide the required pre-tool event.
