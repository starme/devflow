# DevFlow 平台适配契约

DevFlow 由两部分组成：

- **`core/`** —— 平台无关的核心引擎，所有平台共享同一份。
- **adapter（适配层）** —— 针对某个 AI 编码平台（Claude Code / Codex / Cursor / Trae …）的薄胶水，把该平台的扩展机制桥接到 `core/`。

本目录用于存放各平台的适配实现。目前**只有 Claude Code 一个可用适配**（其代码位于插件根目录的 `.claude-plugin/`、`commands/`、`hooks/devflow-hook.*`、`agents/`）。新增平台时，在本目录下建子目录，按本契约实现。

---

## 一、core/ 提供了什么（适配层不需要重写）

| 资源 | 路径 | 消费方式 |
|------|------|---------|
| 工作流引擎 | `core/orchestrator/SKILL.md` | 流程契约（六值状态机、需求锚定协议、Gate、GATE-V 验证、交付守门）。适配层让主 Agent 读取并遵循它；其中 `Task` 派发（仅 `devflow-verifier` 一个 subagent）是 Claude 方言，移植时翻译为目标平台的等价机制，无该机制的平台由主线程自验并在报告标注。 |
| 红线守护 | `core/hooks/redline-guard.py` | 纯标准库 CLI，从 stdin 读 JSON，向 stdout 输出拦截决策。 |
| 审计日志 | `core/hooks/audit-log.py` | 纯标准库 CLI，把操作追加到 `.devflow/runs/<run_id>/audit.log`。 |
| 共享模块 | `core/hooks/devflow_guard_common.py` | 被上面两个脚本导入；负责定位 `core/`、解析 manifest/redlines。 |
| 编码规则 | `core/rules/` | 语言/框架规则（Markdown）。 |
| 项目模板 | `core/templates/` | `project.yaml`、`task.yaml`、`prd.md`、`task-card.md`、`redlines.yaml`、规则模板（`manifest.yaml` 为 legacy 兼容格式）。 |
| 验证 Agent 定义 | `agents/verifier-agent.md`（唯一 subagent，随 Claude 适配） | 正文平台无关，仅 frontmatter（name/tools/model）是 Claude 专属。移植时复制正文、替换 frontmatter；无 subagent 机制的平台不派发，由主线程自验并标注。 |

`core/hooks/*.py` **不 import 任何平台专属模块**，也不假设运行平台。它们通过 `__file__` 自定位 `core/`，并识别 `CLAUDE_PLUGIN_ROOT` 环境变量作为辅助；新增平台可通过设置等价的"插件根目录"环境变量或直接按相对路径调用来复用，无需改动脚本。

项目初始化同样是证据驱动的：`core/project_analyzer.py` 识别传统应用、AI Agent、Agent Plugin、Skill、MCP server 等类别并记录能力。适配层只消费分析结果，不应把所有项目强行映射为 backend/frontend。
---

## 二、一个适配层必须提供的 4 项能力

### 1. 命令入口（Command registration）

把这些用户命令映射到平台的斜杠命令/指令系统：

| 命令 | 行为 |
|------|------|
| `devflow init` | 探测技术栈与类别，生成 `project.yaml` / `redlines.yaml` / 项目规则 |
| `devflow start <需求>` | 走 feature 流程（锚定 Q&A → PRD → 方案卡 → 实现 → 验证 → 交付） |
| `devflow fix <bug>` | 走精简 bugfix 流程（诊断卡 → 修复 → 回归验证 → 交付） |
| `devflow status` | 读取 `project.yaml` / `task.yaml`，报告当前阶段/产物/下一步 |
| `devflow next` | 从中断处继续 |

init 需要知道 `core/` 的绝对路径，以便拷贝模板和规则。Claude 适配用 `CLAUDE_PLUGIN_ROOT` 定位；其他平台用各自的"扩展安装目录"变量。

### 2. Hook 桥接（最关键）

适配层必须在 AI 工具执行**写文件/执行命令**前后，调用 core 的 hook 脚本。

**PreToolUse（红线守护）调用协议：**

stdin JSON（适配层组装）：

```json
{
  "tool_name": "Write",
  "tool_input": { "file_path": "/path/to/target" },
  "cwd": "/current/working/dir"
}
```

- `tool_name` ∈ `Write | Edit | MultiEdit | Bash`
- Bash 时 `tool_input` 含 `command`

stdout：
- **空** → 放行
- JSON `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}` → 拦截，把 reason 展示给用户

**PostToolUse（审计日志）调用协议：**

同样的 stdin JSON（工具执行成功后调用）。脚本无关键输出，追加一行审计记录。

### 3. 验证派发（GATE-V）

v2（ADR-0005）只有唯一 subagent `devflow-verifier`（干净上下文独立验证）。适配层需提供一种机制，让主线程能以"独立上下文 + 受限工具集"的方式派发它，并在完成后收回控制权。

| 平台 | 等价机制 |
|------|---------|
| Claude Code | `Task` 工具 + `agents/verifier-agent.md`（frontmatter 限定 tools/model） |
| Codex CLI | 无 subagent 机制——主线程自验，验证报告标注 "main-thread verification, not an independent verifier" |
| Cursor | 待调研（background agent / custom command） |
| Trae | 待调研（Skill / agent 机制） |

### 4. 任务状态

任务状态自足于 `.devflow/task.yaml`（`task.current_phase` 六值：qa → prd_review → plan_review → working → deliver_confirm → done）。v1 的运行时 `context.json` 已退役（ADR-0005）；适配层调用 hook 时无需额外传参——脚本自行发现状态文件。

---

## 三、能力分级：Hard 模式 vs Soft 模式

不是所有平台都提供"工具执行前拦截"。这直接决定红线防护的强度，必须对用户透明。

| 能力 | 🟢 Hard 模式 | 🟡 Soft 模式 |
|------|-------------|-------------|
| 触发条件 | 平台支持 PreToolUse 等价钩子（工具执行前可同步拦截） | 平台无前置钩子，只能事后/提示词约束 |
| 红线 | **硬拦截**：deny 决策直接阻止写入 | **软约束**：在系统提示中声明红线 + PostToolUse 事后审计/告警 |
| 目录边界 | 硬拦截越界写入 | 提示词约束 + 事后审计 |
| 危险 Bash | 硬拦截 | 提示词约束 |
| 审计日志 | ✅ 完整 | ✅ 完整（事后记录仍可做） |
| 代表平台 | Claude Code | Cursor（待确认）；部分 CLI |

**规则：**
- 适配层在 `devflow init` 时必须探测平台能力，并在 `.devflow/project.yaml` 写入 `adapter.capability: hard | soft`（旧项目才写 `manifest.yaml`）。
- Soft 模式下，编排器在启动时明确告知用户："当前平台不支持前置硬拦截，红线仅为软约束 + 事后审计。"
- Soft 模式不得伪装成 Hard 模式。宁可让用户知道防护降级，也不给出虚假的安全感。

Codex CLI / Trae 是否支持前置钩子，需在实现对应适配前**逐家核实官方文档**，不能假设。

---

## 四、新增适配的步骤

1. 在 `adapters/<platform>/` 下建目录。
2. 实现命令入口（第 2.1 节）。
3. 实现 hook 桥接（第 2.2 节）：
   - 若平台支持前置拦截 → 直接透传 stdin/stdout 给 `core/hooks/redline-guard.py`。
   - 若不支持 → 退化为 soft 模式，在提示词注入红线规则，并在工具执行后调用 `audit-log.py`。
4. 实现 Agent 派发映射（第 2.3 节）。
5. 在 init 流程写入 `adapter.name` 和 `adapter.capability`。
6. 用 `core/hooks/` 的行为作为验收基线：同一条 `echo '{"tool_name":"Write",...}' | python3 core/hooks/redline-guard.py` 在该平台必须产出与 Claude 适配一致的拦截决策。
7. 更新本 README 的适配状态表。

---

## 五、适配状态

| 平台 | 状态 | 能力等级 | 位置 |
|------|------|---------|------|
| Claude Code | ✅ 可用 | 🟢 Hard | 插件根目录（`.claude-plugin/`、`commands/`、`hooks/`、`agents/`） |
| Codex CLI | `adapters/codex/` | 🟡 Soft | `turn/start` skills, MCP tools/hooks, command approval verified; generic file-write pre-hook not verified |
| Cursor | 📋 规划 | 待核实 | — |
| Trae | 📋 规划 | 待核实 | — |

> Codex 的适配实现见 [`codex/`](codex/)。Codex 当前明确声明为 Soft：官方文档确认 Skill、MCP 和命令审批扩展点，但尚未确认通用文件写入前置拒绝 Hook。
