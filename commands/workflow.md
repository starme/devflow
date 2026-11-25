---
description: DevFlow 开发流程 — 新功能与 Bug 修复共用一条路径
argument-hint: [--base <git-ref>] [--source-task <task-id>] <需求或 bug 描述>
---

# /devflow start · /devflow fix

两条路径共用一份流程，差别只有起点：

| | feature（`start`） | bugfix（`fix`） |
|---|---|---|
| 分支前缀 | `feature/` | `fix/` |
| qa 产出 | 需求澄清 | 症状 + 复现 + 根因 |
| 方案文档 | 完整版（11 节） | 瘦版：删需求明细与核心诉求，保留原话症状、根因、回归标准 |
| 其余 | 完全相同 | 完全相同 |

## 前置检查

1. 确认当前目录位于 Git 仓库，且项目已 `/devflow init`（读 `.devflow/project.yaml`；旧项目兼容读 `manifest.yaml`，不覆盖旧状态）。
2. 主工作区**没有**活动 task 时：已跟踪改动必须干净（临时修改不带进新分支）。
3. 主工作区**已有**活动 task 时：拒绝再开，提示先 `/devflow next` 完成或归档该 task。所有 task 串行在主工作区进行。
4. 同一 task 重复 start 才拒绝。
5. bug 只存在于未合并需求时，要求用户明确 `--base <branch>`；`--source-task` 只记录来源，不建依赖图。
6. 只读对照主分支（查线上）不用本命令，用临时 `git worktree add` 或 `git show`。（与 task 隔离无关，不受影响）

## 创建 task

```text
/devflow start "需求描述" [--base <git-ref>]
/devflow fix [--base <git-ref>] [--source-task <task-id>] "bug 描述"
```

用 `core/orchestrator/worktree_manager.py` 的 `create_task`，**启动目录**（持有 `.devflow/` 的那个目录）即项目根：

1. `project_root` = 启动目录本身，不向上查找 `.devflow`；从子仓启动而该子仓没有自己的 `.devflow` 时视为未初始化（提示 `/devflow init`）。
2. 生成唯一 `task_id`、slug 与分支名 `feature|fix/<slug>-<short-id>`，写 `<project_root>/.devflow/task.yaml`（`current_phase: qa`，fix 记 `kind: bugfix`）。
3. **git 可选**：启动目录是 git 仓时建分支、冻结 `git.base_commit`（`--base` 或当前分支）；不是 git 仓时跳过 git 操作并打印提示（`workspace.git_policy: auto_skip` 可关闭提示）。`git.working_dir` 记录启动目录。
4. 多仓库：仅当 `project.yaml` 在**启动目录**声明 `workspaces:` 时生效——每端点同名分支、各自 `base_commit`，交付时各开一个 PR。端点必须自身是 git 仓，否则报错；从子仓启动不跨仓。
5. 向用户报告 task id、分支（无 git 时说明已跳过）、`working_dir`、base commit（无则为空）。

## 执行

加载 `core/orchestrator/SKILL.md`，按流程契约推进：

1. **qa**
   - feature：原话逐字冻结进方案文档第 1 节 → 2-3 句复述核心诉求获确认 → 填空式提问 → `[推断]` 条目显式确认。
   - fix：冻结原话症状 → 复现步骤 → 根因定位。
2. **设计时召回**：写方案文档之前调一次 `memorant_recall`，结果填进第 4 节「历史经验」（空也要写「无相关历史」，不许删节）。
3. 写 `.devflow/plan.md`（模板 `core/templates/plan.md`）：需求明细带来源 + 历史经验 + **备选方案与否决理由（至少两个）** + 实现要点 + 验收标准表（映射 R#）。fix 用瘦版。
4. **plan_review（GATE-PLAN）**：展示方案文档，重点给来源 ≠ 原话的行，等用户批准。批准即冻结，同时写回一条 `plan_pattern`。
5. **working**：直接实现，勾进度；方案之外的问题写进「待办支线」不修；按四个触发条件召回并写进「踩坑记录」。
6. **QA**：派 `devflow:devflow-verifier` → `.devflow/verification-report.md`。FAIL 自己修后重派，连续 3 轮失败停下报告。
7. **review**：派 `devflow:devflow-reviewer` → `.devflow/review-report.md`。把结论摆给用户，**由用户决定修还是直接交付**。
8. **deliver_confirm（GATE-DELIVERY）**：探测 + 归档 + 一次三合一确认 → commit + push + PR。**PR 创建后暂停，永不自动 merge。**
9. **distill**：把「踩坑记录」逐条写回 `bug_pattern`（`verified`）；Memorant 不可用写 `.devflow/retrospective.md`。PR 合并后 `/devflow next` 做清理。

## 注意

- 需求澄清在当前会话完成；派发的只有 `devflow:devflow-verifier` 和 `devflow:devflow-reviewer`。
- Gate 等人时停；其余阶段直接干到下一个 Gate，不要求用户打 `/devflow next`。
- 不自动 merge。交付确认通过后才 push 和创建 PR。
- Memorant 不可用时静默降级，不阻塞流程。
- bug 属于当前需求时可显式 `--parent <task-id>` 作追溯信息；代码基准仍由 `--base` 决定。
