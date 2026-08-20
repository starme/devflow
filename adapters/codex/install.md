# Codex adapter installation

## CLI / Skill mode

1. Make the DevFlow repository available to Codex.
2. Copy or link `adapters/codex/AGENTS.md` at the project root, or merge its instructions into the existing `AGENTS.md` without replacing project-specific rules.
3. Register `adapters/codex/devflow-codex.md` as a Codex Skill named `devflow`.
4. Run the equivalent of `devflow init` from the target repository. Confirm the reported category and tracks when the result is ambiguous.
5. Use the Skill with `devflow start`, `devflow fix`, `devflow status`, and `devflow next` inputs.

## app-server mode

Send a `turn/start` request with a text input containing `$devflow` and a skill input item pointing to `devflow-codex.md`. The host must provide the thread and turn identifiers and route command-approval requests back to the user.

## Safety

Set Codex sandbox and approval policy according to the host's security requirements. The adapter capability is `soft`: Codex's documented command approval and MCP hooks do not prove a generic file-write pre-tool deny hook. The Manager must display that limitation. Core audit logging remains required after actions.

## Verification

Run:

```bash
python3 -m unittest discover -s core/tests -v
python3 -m unittest discover -s adapters/codex/tests -v
```

A live app-server check is `BLOCKED` when Codex is not installed or authenticated; do not report it as a passing integration test.
