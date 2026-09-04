---
description: Initialize DevFlow project — detect stack, configure paths, generate project configuration
---

# /devflow init

初始化 DevFlow 项目配置。项目长期事实与每个需求的运行状态分离保存。

## 定位插件目录

按原有方式定位 `$DEVFLOW_ROOT`，确认 `core/templates/project.yaml`、`core/templates/task.yaml`、`core/templates/context.json` 和 `core/rules/engineering.md` 存在。找不到时提示运行 `bash install.sh`。

## Step 1: Evidence-based project analysis

使用共享 `core/project_analyzer.py` 扫描安全仓库证据，不读取 `.env*`、密钥、凭证或私钥。识别：

- traditional_application
- ai_agent_application
- agent_plugin
- skill
- mcp_server
- ai_tool_or_workflow
- library_or_other

如果置信度低或候选接近，展示证据并请求用户确认，不静默选择不匹配轨道。

## Step 2: 写入项目级配置

创建 `.devflow/project.yaml`，只写跨需求稳定的内容：项目名称、分类/置信度/证据、capabilities、workspace 路径、支持的 adapter、安全规则和 Memorant project key。`project.yaml` 不得包含当前 phase、需求描述、分支、worktree、PRD、测试轮次或某个 Agent 的 cwd。

将项目能力全集写入 `project.capabilities`。`workflow.selected_tracks` 不写入项目配置；它属于某个 task，由架构阶段根据本次需求选择。

如果项目已有旧 `.devflow/manifest.yaml`，不删除、不静默覆盖；旧命令通过兼容适配器继续读取。

## Step 3: 生成项目规则

按原有流程创建 `.devflow/rules/project.md`、存在后端/前端时创建对应规则，复制 `.devflow/redlines.yaml`。这些是项目级策略，任务只引用它们，不放入 task 状态。

## Step 4: 创建项目目录

```bash
mkdir -p .devflow/contracts docs docs/adr
```

新任务由 `/devflow start` 或 `/devflow fix` 创建：默认在主工作区功能分支上写 `.devflow/task.yaml`；只有主工作区已有未完成 task 时，后来者才进 `.devflow-worktrees/`。`context.json` 和 `runs/` 属于运行时，不应成为共享项目状态。

## Step 5: 兼容说明

为旧项目保留 `.devflow/manifest.yaml` 读取路径。旧 manifest 映射为内存中的 legacy project/task view，不在本步骤强制迁移。新任务用 `project.yaml` + 该 task 的 `task.yaml`。

## Step 6: 完成报告

报告项目类别、证据、capabilities、workspace、adapter/redline 能力、Memorant 状态，以及下一步：

```text
/devflow start "需求描述"
/devflow fix "bug 描述"
```

Codex 的 redline 能力如果为 soft，必须明确说明仅有审批/提示词约束和事后审计，不能声称具备 Claude Code 的 hard PreToolUse 文件写入拦截。
