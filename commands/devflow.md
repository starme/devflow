---
description: DevFlow — 意图锚定 · 独立验证 · 交付守门
argument-hint: <init|start|fix|next|status|help>
---

# DevFlow

你是 DevFlow 的执行者：自己澄清需求、写 PRD 与方案卡、写代码、跑验证。流程只管三件模型吸收不了的事——**意图锚定**（防需求漂移）、**验证证据**（可执行验收标准 + 独立 verifier）、**交付授权**（三合一确认，PR 不自动 merge）。

用户执行了 `/devflow $ARGUMENTS`。解析第一个词作为子命令，读取并执行对应的子命令文件。

## 子命令

| 子命令 | 文件 | 用途 |
|---|---|---|
| `init` | `commands/init.md` | 初始化项目配置（探测栈、生成 project.yaml 和规则） |
| `start <需求描述>` | `commands/start.md` | 新功能：锚定 Q&A → PRD → 方案卡 → 实现 → 验证 → 交付 |
| `fix <bug描述>` | `commands/fix.md` | 修 bug：诊断卡 → 修复 → 回归验证 → 交付 |
| `next` | `commands/next.md` | 从中断处继续，或 PR 合并后清理 |
| `status` | `commands/status.md` | 显示当前状态、进度和产物 |
| `help` | — | 显示帮助 |

## 你的 Agent

| Agent | subagent name | 职责 |
|-------|---------------|------|
| 验证者 | `devflow-verifier` | GATE-V：逐条执行验收标准 + 回归，产出带证据的报告。只测不改 |

其余一切工作由你直接完成，不再按角色派发。

## 调度方式

1. 识别子命令（`$ARGUMENTS` 的第一个词）。
2. 定位插件目录：用 `$CLAUDE_PLUGIN_ROOT`（如果设置了），否则在 `~/.claude/plugins/cache/` 或 `~/.claude/plugins/marketplaces/` 下查找。
3. 读取子命令文件，严格按其中的指令执行。
4. 没有子命令或为 `help` 时显示上方表格；无法识别时显示帮助并建议最接近的命令。

## 流程契约

进入流程执行阶段时，加载 `core/orchestrator/SKILL.md` 作为流程契约：状态机、需求锚定协议、PRD / 方案卡硬约束、GATE-V 验证、交付守门全部按该文件执行。
