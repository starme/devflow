---
description: Bug 修复模式 — 独立 task/worktree 定位→修复→回归测试
argument-hint: [--base <git-ref>] [--source-task <task-id>] <bug 描述>
---

# /devflow fix

Bug 修复 / 日常维护模式。默认创建独立 bugfix task/worktree，不污染当前正在开发的其他需求。

## 前置检查

1. 确认项目已初始化：优先读取 `.devflow/project.yaml`，旧项目兼容读取 `.devflow/manifest.yaml`。
2. 确认主仓库 Git 状态干净；不把当前需求 worktree 或临时修改静默作为 bugfix 基准。
3. 默认从主分支（或显式 `--base <git-ref>`）创建独立 worktree。
4. 如果 bug 只存在于未合并需求，要求用户明确 `--base <branch>`；`--source-task <task-id>` 仅记录问题来源，不建立依赖图。

## 创建隔离 task

```text
/devflow fix [--base <git-ref>] [--source-task <task-id>] "bug 描述"
```

1. 生成唯一 task id 和 `fix/<slug>-<short-id>` 分支。
2. 固化 `git.base_ref` 和 `git.base_commit`。
3. 创建仓库外独立 worktree。
4. 写入该 worktree 的 `.devflow/task.yaml`：`kind: bugfix`、描述、基准、分支、worktree，以及可选 `source_task_id`。
5. 创建 task 专属 `.devflow/context.json`。

## 执行流程

在 bugfix task worktree 内按精简流程执行：

```text
CLASSIFY → ARCHITECTURE/DIAGNOSIS → DEVELOPMENT → TESTING → DISTILL → DONE
```

- 架构 Agent 只分析根因，输出 `.devflow/diagnosis.md` 和 `.devflow/scope.yaml`。
- 研发 Agent 先写可复现 bug 的回归测试，再针对根因修复。
- 测试 Agent 运行回归与分层测试，失败最多自动路由 3 轮。
- 纯文档/配置 bug 可免回归测试，但必须在报告中说明原因。
- 不自动 merge、push、删除分支或 worktree。

## 当前需求内的修复

如果 bug 属于当前需求而不是独立交付，可显式使用 `--parent <task-id>` 作为可选追溯信息。第一版不实现通用 task relation 或依赖调度；代码基准仍由 `--base` 和 `git.base_commit` 决定。
