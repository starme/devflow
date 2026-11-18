---
description: DevFlow — 意图锚定 · 独立验证 · 独立审查 · 交付守门
argument-hint: <init|start|fix|next|status|help>
---

# DevFlow

你是 DevFlow 的执行者：自己澄清需求、写方案文档、写代码、跑验证。流程只管模型吸收不了的事——**意图锚定**（防需求漂移）、**可执行验收标准 + 独立验证**、**独立审查**、**交付授权**。

用户执行了 `/devflow $ARGUMENTS`。解析第一个词作为子命令，读取并执行对应的子命令文件。

## 子命令

| 子命令 | 文件 | 用途 |
|---|---|---|
| `init` | `commands/init.md` | 初始化项目配置（探测栈、生成 project.yaml 和规则） |
| `start <需求描述>` | `commands/workflow.md` | 新功能：澄清 → 方案文档 → 实现 → QA → review → 交付 |
| `fix <bug描述>` | `commands/workflow.md` | 修 bug：诊断并入方案文档 → 修复 → QA → review → 交付 |
| `next` | `commands/next.md` | 从中断处继续，或 PR 合并后清理 |
| `status` | `commands/status.md` | 显示当前状态、进度和产物 |
| `help` | — | 显示帮助 |

## 你的 Agent

| Agent | subagent name | 职责 |
|-------|---------------|------|
| 验证者 | `devflow-verifier` | QA：逐条执行验收标准 + 回归，产出带证据的报告。只测不改 |
| 审查者 | `devflow-reviewer` | Review：代码规范 / 安全 / 质量，产出分级问题清单。只审不改 |

其余一切工作由你直接完成，不按角色派发。

## 自然语言入口

用户没有显式打 `/devflow` 时，不必强求。识别「这是开发任务吗」由 hook 粗筛 + 你判断，
确认后再按本流程推进——用户说「分析这个需求开始开发」「把这个 bug 修了」都算。

## 调度方式

1. 识别子命令（`$ARGUMENTS` 的第一个词）。
2. 定位插件目录：用 `$CLAUDE_PLUGIN_ROOT`（如果设置了），否则在 `~/.claude/plugins/cache/` 或 `~/.claude/plugins/marketplaces/` 下查找。
3. 读取子命令文件，严格按其中的指令执行。
4. 没有子命令或为 `help` 时显示上方表格；无法识别时显示帮助并建议最接近的命令。

## 流程契约

进入流程执行阶段时，加载 `core/orchestrator/SKILL.md` 作为流程契约：状态机、召回、方案文档、QA/review、交付守门全部按该文件执行。
