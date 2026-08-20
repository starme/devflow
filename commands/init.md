---
description: Initialize DevFlow project — detect stack, configure paths, generate rules and manifest
---

# /devflow init

初始化 DevFlow 项目配置。自包含，不依赖外部 `/init` 命令。按顺序执行。

## 定位插件目录

```bash
if [ -n "$CLAUDE_PLUGIN_ROOT" ] && [ -d "$CLAUDE_PLUGIN_ROOT" ]; then
  DEVFLOW_ROOT="$CLAUDE_PLUGIN_ROOT"
else
  DEVFLOW_ROOT=$(find ~/.claude/plugins/cache -maxdepth 4 -type d -name "devflow" 2>/dev/null | head -1)
  if [ -z "$DEVFLOW_ROOT" ]; then
    [ -d "$HOME/.claude/plugins/marketplaces/devflow-marketplace" ] && \
      DEVFLOW_ROOT="$HOME/.claude/plugins/marketplaces/devflow-marketplace"
  fi
  if [ -z "$DEVFLOW_ROOT" ]; then
    DEVFLOW_ROOT=$(find ~/.claude/plugins/marketplaces -maxdepth 3 -type d -name "devflow" 2>/dev/null | head -1)
  fi
fi
echo "DEVFLOW_ROOT=$DEVFLOW_ROOT"
ls "$DEVFLOW_ROOT/core/templates/manifest.yaml" "$DEVFLOW_ROOT/core/rules/engineering.md"
```

使用结果作为 `$DEVFLOW_ROOT`。找不到则提示用户运行 `bash install.sh`。

## Step 1: Evidence-based project analysis

Do not assume that every repository is a traditional backend/frontend application. Analyze the repository root with the shared `core/project_analyzer.py` module and classify it from safe, explainable evidence:

- `traditional_application`
- `ai_agent_application`
- `agent_plugin`
- `skill`
- `mcp_server`
- `ai_tool_or_workflow`
- `library_or_other`

The analyzer must inspect repository markers such as plugin manifests, `SKILL.md`, `AGENTS.md`, commands, hooks, MCP configuration/SDK references, prompt/evaluation directories, application manifests, and documentation. It must never read `.env*`, credentials, secrets, or private keys.

Persist all of the following in `project` in the manifest:

- `category`
- `category_confidence`
- `category_ambiguous`
- `category_evidence[]`
- `capabilities[]`

Persist the selected lifecycle tracks under `workflow.tracks`. Track selection is category-aware. Traditional applications retain backend/frontend/API tracks; Agent Plugin, Skill, MCP, and AI Agent projects use only applicable plugin, command, skill, agent, prompt, hook, tool, integration, evaluation, packaging, documentation, and testing tracks. Do not create empty backend/frontend tracks for projects that do not contain them.

If confidence is low or the top categories are close, show the ranked candidates and evidence and ask the user to confirm the category before writing the final manifest. Do not silently make an incompatible choice.

## Step 2: Generate CLAUDE.md

如果项目根目录没有 `CLAUDE.md`，生成一个简洁版本：

```markdown
# {项目名}

## 项目概述
- 技术栈：{后端框架} + {前端框架} + {数据库}
- 后端路径：{BACKEND_PATH}
- 前端路径：{FRONTEND_PATH}

## 常用命令
- 后端测试：{探测到的命令}
- 前端测试：{探测到的命令}
- 构建：{探测到的命令}
- Lint：{探测到的命令}

## DevFlow
本项目使用 DevFlow 管理开发流程。配置见 .devflow/manifest.yaml。
- 新功能：/devflow start "需求描述"
- 修 bug：/devflow fix "bug 描述"
- 查看状态：/devflow status
- 继续中断流程：/devflow next
```

读取现有代码填充细节，只问真正缺失的关键信息。

## Step 3: 创建项目自定义规则（三层 Rules 的第二层）

创建 `.devflow/rules/` 目录，从模板生成项目规则文件：

```bash
mkdir -p .devflow/rules
cp "$DEVFLOW_ROOT/core/templates/rules-project.md" .devflow/rules/project.md
```

如果有后端：
```bash
cp "$DEVFLOW_ROOT/core/templates/rules-backend.md" .devflow/rules/backend.md
```
替换 `{{BACKEND_LANG}}`、`{{BACKEND_FRAMEWORK}}`、`{{DATABASE}}` 占位符。

如果有前端：
```bash
cp "$DEVFLOW_ROOT/core/templates/rules-frontend.md" .devflow/rules/frontend.md
```
替换 `{{FRONTEND_FRAMEWORK}}` 占位符。

**不复制内置规则到项目目录**（方案 C）。内置规则留在插件目录，Agent 执行时按需加载，插件升级自动生效。项目规则文件只写差异和补充。

同时复制通用工程规则到用户级目录（如果不存在）：
```bash
mkdir -p ~/.claude/rules
cp -n "$DEVFLOW_ROOT/core/rules/engineering.md" ~/.claude/rules/engineering.md
```

## Step 4: 创建 .devflow 目录和 manifest

```bash
mkdir -p .devflow/contracts docs docs/adr
```

复制 manifest 模板并替换占位符：
```bash
cp "$DEVFLOW_ROOT/core/templates/manifest.yaml" .devflow/manifest.yaml
```

复制红线规则文件（PreToolUse hook 会读取此文件进行硬拦截）：
```bash
cp "$DEVFLOW_ROOT/core/templates/redlines.yaml" .devflow/redlines.yaml
```
此文件从默认模板复制，用户可自行编辑添加项目特定的保护规则。修改后立即生效，无需重启。

替换以下占位符：
- `{{PROJECT_NAME}}` → 项目目录名
- `{{CREATED_AT}}` → 当前 ISO 时间戳
- `{{PROJECT_ROOT}}` → 项目根目录绝对路径
- `{{BACKEND_PATH}}` → 探测到的后端路径（无后端则为 `null`）
- `{{BACKEND_STACK}}` → `{lang}/{framework}`（如 `go/gin`，无后端则为 `null`）
- `{{FRONTEND_PATH}}` → 探测到的前端路径（无前端则为 `null`）
- `{{FRONTEND_STACK}}` → 前端框架（如 `react/vite`，无前端则为 `null`）
- `{{ADAPTER_NAME}}` → 平台适配层标识（Claude Code 为 `claude-code`）
- `{{ADAPTER_CAPABILITY}}` → 红线防护等级（见下方探测说明）

如果某个栈不存在，对应字段设为 YAML 的 `null`（不是字符串 "null"）。

### 写入 adapter 能力等级

探测当前平台是否提供 PreToolUse 前置钩子（工具执行前可同步拦截），据此写入 `adapter.capability`：

- **Claude Code**：插件已注册 PreToolUse 钩子（见 `.claude-plugin/plugin.json`），`capability` 固定为 `hard`。
- **其他平台**（Codex / Cursor / Trae）：按该平台适配层是否实现前置拦截为准。支持则 `hard`，否则 `soft`。

写入结果示例（Claude Code）：

```yaml
adapter:
  name: "claude-code"
  capability: "hard"
```

若为 `soft`，在 Step 7 向用户报告时明确提示：当前平台不支持前置硬拦截，红线仅为软约束 + 事后审计。

## Step 5: 检查 Memorant 可用性

检查 Memorant 插件是否已安装（查看 `~/.claude/plugins/installed_plugins.json` 或已启用插件列表中是否含 "memorant"）。

- 已安装：manifest 中 `memorant.enabled` 保持 `auto`，运行时会自动检测 MCP 工具。
- 未安装：不阻塞。DevFlow 静默降级为纯 Markdown 模式。

## Step 6: .gitignore 检查

建议在 `.gitignore` 中添加：
```
.devflow/contracts/
```
`.devflow/manifest.yaml`、`.devflow/redlines.yaml` 和 `.devflow/rules/` 建议提交（团队共享状态、规则和红线配置）。

## Step 7: 完成

向用户报告初始化结果：
- 探测到的技术栈和路径
- 生成的文件列表（CLAUDE.md、manifest、redlines、rules）
- 红线规则：`.devflow/redlines.yaml` 已生成，PreToolUse hook 将自动拦截对密钥/CI/依赖文件的未授权修改
- Memorant 状态（可用/降级）
- 下一步：`/devflow start "你的需求"` 开始新功能，或 `/devflow fix "bug 描述"` 修复问题
