---
description: Bug 修复模式 — 定位→修复→回归测试
argument-hint: [--base <git-ref>] [--source-task <task-id>] <bug 描述>
---

# /devflow fix

Bug 修复 / 日常维护。主工作区没有未完成需求时，fix 也在主工作区进行；若正在做另一个需求，fix 作为后来者进隔离 worktree，不搬开先到的需求。

## 前置检查

1. 确认项目已初始化：优先读取 `.devflow/project.yaml`，旧项目兼容读取 `.devflow/manifest.yaml`。
2. 主工作区没有活动 task 时：Git 已跟踪改动必须干净。
3. 主工作区已有活动 task 时：不要求干净；新 fix 从 `--base`（默认主分支）拉隔离 worktree。
4. 如果 bug 只存在于未合并需求，要求用户明确 `--base <branch>`；`--source-task <task-id>` 仅记录问题来源，不建立依赖图。

## 创建 task

```text
/devflow fix [--base <git-ref>] [--source-task <task-id>] "bug 描述"
```

1. 生成唯一 task id 和 `fix/<slug>-<short-id>` 分支。
2. 固化 `git.base_ref` 和 `git.base_commit`。
3. 调用 `create_task`：in-place 或后来者 worktree，规则与 `/devflow start` 相同。
4. 写入 `.devflow/task.yaml`：`kind: bugfix`、描述、基准、分支、工作区路径，以及可选 `source_task_id`。
5. 写入 `.devflow/context.json`（含 `project_root`、`repo_root`）。

只读查线上不要走本命令。

## 执行流程

在该 task 的工作区内按精简流程执行：

```text
CLASSIFY → ARCHITECTURE/DIAGNOSIS → DEVELOPMENT → TESTING → DELIVERY → DISTILL → DONE
```

- 架构 Agent 只分析根因，输出 `.devflow/diagnosis.md` 和 `.devflow/scope.yaml`。
- 研发 Agent 先写可复现 bug 的回归测试，再针对根因修复。
- 测试 Agent 运行回归与分层测试，失败最多自动路由 3 轮。
- 纯文档/配置 bug 可免回归测试，但必须在报告中说明原因。
- DELIVERY：与 feature 相同的 commit + push + PR 三合一确认；PR 创建后暂停不自动合并。回归确认通过即进入 DELIVERY。
- 自动阶段由 Stop hook 续跑到 Gate / 交付确认，不要让用户打 `/devflow next` 才能继续。
- 过程物料在 DELIVERY 归档到 `.devflow/tasks/<task-id>/`。
- 不自动 merge。PR 合并后 `/devflow next` 再清理后来者 worktree（若有）并切回 base_ref。

## 当前需求内的修复

如果 bug 属于当前需求而不是独立交付，可显式使用 `--parent <task-id>` 作为可选追溯信息。第一版不实现通用 task relation 或依赖调度；代码基准仍由 `--base` 和 `git.base_commit` 决定。
