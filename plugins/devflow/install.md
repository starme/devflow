# DevFlow Codex Plugin installation

## Marketplace-first installation

From the DevFlow repository checkout, add the repository-local marketplace:

```bash
codex plugin marketplace add .
codex plugin list --marketplace devflow-marketplace
codex plugin add devflow@devflow-marketplace
```

For a GitHub checkout, use the repository shorthand:

```bash
codex plugin marketplace add starme/devflow --ref main
codex plugin list --marketplace devflow-marketplace
codex plugin add devflow@devflow-marketplace
```

Open a new Codex thread after installation so the new Skill is discovered. In the target project, invoke:

```text
$devflow init
$devflow status
```

## Fallback for development

If the installed Codex version does not support marketplace installation or sparse marketplace sources, copy `plugins/devflow/skills/devflow/SKILL.md` into `~/.codex/skills/devflow/SKILL.md` and merge `adapters/codex/AGENTS.md` into the target project's `AGENTS.md`. This is a compatibility/development path, not the primary user installation path.

## Verification

```bash
codex plugin list --available --json
codex plugin list --json
```

A live marketplace check is `BLOCKED` if Codex is unavailable or unauthenticated; do not report it as PASS.
