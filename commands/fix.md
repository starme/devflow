---
description: Bug 修复模式 — 诊断卡 → 修复 → 回归验证
argument-hint: [--base <git-ref>] [--source-task <task-id>] <bug 描述>
---

# /devflow fix

Bug 修复 / 日常维护：诊断 → 方案卡（瘦版）→ 一个 Gate → 修复 → 回归验证 → 交付。

## 前置检查

1. 确认项目已初始化：优先读取 `.devflow/project.yaml`，旧项目兼容读取 `.devflow/manifest.yaml`。
2. 主工作区没有活动 task 时：Git 已跟踪改动必须干净。
3. 主工作区已有活动 task 时：不要求干净；新 fix 从 `--base`（默认主分支）拉隔离 worktree。
4. bug 只存在于未合并需求时，要求用户明确 `--base <branch>`；`--source-task <task-id>` 仅记录问题来源，不建立依赖图。

## 创建 task

```text
/devflow fix [--base <git-ref>] [--source-task <task-id>] "bug 描述"
```

`create_task` 同 `/devflow start`：唯一 task id、`fix/<slug>-<short-id>` 分支、固化 `git.base_commit`、in-place 或后来者 worktree、写 `.devflow/task.yaml`（`kind: bugfix`、`current_phase: qa`）。

## 执行

加载 `core/orchestrator/SKILL.md`，fix 的精简路径（跳过 PRD 与 GATE-1）：

1. **qa（诊断）**：冻结原话症状（逐字）→ 复现步骤 → 根因定位（Memorant 召回相似 bug + 代码分析）。
2. 写 `.devflow/card.md` 瘦版：原话症状（冻结）/ 复现步骤 / 根因 / 修复方案 / 回归标准（先写能复现 bug 的回归测试再修复；纯文档/配置 bug 可免回归但必须说明原因）/ 影响范围。回归标准同样分 `cmd` / `ai` / `manual` 并可执行。
3. **plan_review（GATE）**：展示诊断卡，等用户批准。
4. **working**：主线程修复 + 回归，派 `devflow-verifier` 验证（同 feature 的 GATE-V）。
5. **deliver_confirm**：与 feature 相同的三合一确认；PR 创建后暂停不自动合并。
6. PR 合并后 `/devflow next` 清理（后来者 worktree 若有）并切回 base_ref。

## 当前需求内的修复

bug 属于当前需求而不是独立交付时，可显式 `--parent <task-id>` 作为追溯信息；代码基准仍由 `--base` 和 `git.base_commit` 决定。
