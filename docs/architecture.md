# DevFlow 架构说明

> 本文描述**现行**架构（ADR-0005 / ADR-0006 之后）。历史演进见文末「历史演进」一节；
> 流程细节以 `core/orchestrator/SKILL.md` 与 `docs/workflow.md` 为准，决策依据见 `docs/adr/`。

DevFlow 是 Claude Code 上的生命周期编排插件（命令、Agent、Hook、YAML 契约）。人只在 Gate 拍板；中间自动把一个需求做完并开出 PR。任意 git 仓库都能编，`backend` / `frontend` 是可选 track。

核心结构：

| 层 | 位置 | 职责 |
|----|------|------|
| 命令 | `commands/` | `/devflow init\|start\|fix\|status\|next`（start 与 fix 共用 `workflow.md`） |
| 编排 | `core/orchestrator/` | SKILL、task 状态、worktree、交付、归档 |
| Guard | `core/hooks/`、`hooks/` | 红线、审计、Gate 提示（hook 只提示不拦截） |
| 专职 Agent | `agents/` | `verifier-agent.md`（QA）、`reviewer-agent.md`（Review，ADR-0006） |
| 项目状态 | `<project_root>/.devflow/project.yaml` + `task.yaml` | 仓库级配置 vs 当前需求阶段 |
| 归档 | `<project_root>/.devflow/tasks/<task-id>/` | 只在 GATE-DELIVERY 发布过程物料 |

隔离一律 in-place（主工作区功能分支）。主工作区已有未完成 task 时，新 task 被**拒绝**（提示先完成或归档），不再隔离到 `.devflow-worktrees/<repo>/<task-id>`——该布局已退役，仅作历史 task 的只读兼容。过程物料不是每个里程碑都 publish。

**状态归属：启动目录（项目根）是唯一权威。** 持有 `.devflow/` 的目录就是 `project_root`，`task.yaml` 与归档都写在那里；`git` 仓根与项目根可以不同（嵌套子仓场景），但 `create_task` **不做向上查找**——`project_root` 由调用方显式传入，省略时取 `worktree_manager.resolve_project_root`（委托 `core/workspace.py`，目录无 `.devflow/` 时回退为输入目录本身；「未初始化」由调用方前置检查拒绝）。`artifact_publish` 接收两个必填权威源：`--root`（`project_root`，归档权威）与 `--repo-root`（live 状态权威），按 task id 在两处定位 `task.yaml`，写入 `<project_root>/.devflow/tasks/<task-id>/`。hooks 的 `resolve_session_project_root` 与编排的 `resolve_project_root` 共享「不向上查找」原则并各自委托 `core/workspace.py`，但入口与缺省语义不同。从子仓启动而该子仓没有自己的 `.devflow/` 时视为**未初始化**（提示 `/devflow init`），父级 `.devflow/` 不会接管；多仓 `workspaces:` 能力只属于声明它的那个目录。

---

## 一、状态机与用户确认点

### 1.1 五值状态机

`task.current_phase` 取 5 个值，只用于提示注入，**hook 永不拦截**：

```text
qa → plan_review → working → deliver_confirm → done
```

| 值 | 含义 | 谁推进 |
|---|------|--------|
| `qa` | 需求澄清或 bug 诊断 | 主线程 ↔ 用户 |
| `plan_review` | GATE-PLAN：等人审方案文档 | 等用户 |
| `working` | 实现 → QA → review | 主线程 |
| `deliver_confirm` | GATE-DELIVERY：等人确认交付 | 等用户 |
| `done` | PR 已合并、清理完成 | — |

每需求人只出现 **2 次**（方案冻结、交付确认）。其余阶段一口气干到下一个 Gate；`/devflow next` 只用于会话中断恢复与 PR 合并后的清理。旧值 `prd_review` 映射为 `plan_review`。

### 1.2 GATE-DELIVERY：一次三合一确认

进入 `deliver_confirm` 后，主线程**一次性**向用户列出：待提交清单（白名单过滤）、目标分支、remote 与 push 目标、PR 标题/描述预览、验证摘要、review 摘要、manual 项、待办支线，并询问一次：**「是否 commit + push + 创建 PR？」**

- 用户仅回复「通过 / 同意 / 确认」→ 默认三者全执行。
- 用户有其他意见（如「先只提交不 push」「PR 标题改成…」）→ 按需调整，不擅自决定。
- **PR 创建后暂停，永不自动 merge**；merge 由用户在平台上完成。

### 1.3 双子状态文件

- **`task.yaml`**（`core/orchestrator/task_state.py`）：task 身份、`current_phase`/`status`、`git` 段（base_ref/base_commit/branch/working_dir，多仓时含 `endpoints` 候选列表与 `activated` 标记）、parent/source 追溯、`artifacts` 引用。
- **`.devflow/delivery.yaml`**（`core/orchestrator/delivery.py`）：独立交付子状态，`task.yaml` 仅在 `artifacts.delivery` 引用它。字段全部可判定，`/devflow next` 据此幂等恢复：

```yaml
delivery:
  commit: null          # 交付 commit 的 short hash
  pushed: false         # 分支是否已 push
  remote: "origin"
  pr_url: null
  pr_title: null
  worktree_removed: false  # in-place 任务恒 true（无额外 worktree）
  branch_deleted: false    # 本地分支是否已删除
  returned_to_main: false  # 是否已切回 base_ref
  repos: []                # 多仓时每端点的 commit/pushed/pr_url
```

`TaskRecord` 是 frozen dataclass，`load_task` 只解析标量字段；交付状态刻意不进 `TaskRecord`，避免破坏 round-trip 测试。

---

## 二、交付流程（主线程执行）

### 2.1 commit 文件白名单

提交前用白名单过滤 `git status --porcelain`：

**允许提交：**
1. 所有已跟踪文件的改动（`M` / `A` / `D`）
2. `docs/**` 下已跟踪的文档（`docs/architecture.md`、`docs/workflow.md`、`docs/adr/*.md`、`README*.md`）
3. `.devflow/**` 中在 `DELIVERY_ARTIFACT_FILES` 白名单内的产物

**禁止提交：**
- 临时文件、编辑器残留、`*.tmp`、`*.log`
- 退役的 `.devflow/context.json`（v2 起不再写入；`DELIVERY_SKIP_FILES` 仍防御性排除遗留文件）
- `.devflow/runs/**`（审计日志，不进交付）
- 未跟踪且不在 `.devflow` 白名单内的文件

**`DELIVERY_ARTIFACT_FILES`（权威定义在 `core/orchestrator/delivery.py`；guard 的 `_DEVFLOW_ARTIFACT_FILES` 是其超集，另含 guard-only 的 `frontend-components.md` / `impact-analysis.md`；一致性由 `test_delivery.py` 校验）：**

```text
.devflow/scope.yaml
.devflow/prd.md
.devflow/card.md
.devflow/plan.md
.devflow/review-report.md
.devflow/verification-report.md
.devflow/memorant-journal-investigation.md
.devflow/architecture.md
.devflow/diagnosis.md
.devflow/acceptance-report.md
.devflow/acceptance-scenarios.md
.devflow/test-report.md
.devflow/task-report.md
.devflow/backend-task-report.md
.devflow/frontend-task-report.md
.devflow/pr.md
.devflow/delivery.yaml
.devflow/retrospective.md
```

### 2.2 commit 规范

- Conventional Commits：`feat: ...` / `fix: ...` / `refactor: ...` / `docs: ...`，imperative mood。
- 由主线程汇总本次改动生成 message，不照搬 task 描述原文，避免超长。

### 2.3 push 与 PR 创建

- push：首次设上游。**已知假阳性**（有回归测试固定，见 `test_redline_guard.py::test_branch_name_with_f_token_triggers_force_push_false_positive`）：guard 的 force-push 正则会把分支名里的 `-f-<id>` token 误判为 `-f` 标志；等价形式 `git push origin HEAD` + `git branch --set-upstream-to` 不触发。修 guard 正则属独立变更，须同步该测试。
- PR 创建成功后写 `.devflow/pr.md`（URL、标题、base/head、时间戳）。
- **PR 创建后暂停，不自动合并**。

### 2.4 清理与返回主分支（PR 合并后）

PR 创建后**不自动清理**——清理发生在 PR 合并、用户确认后（`/devflow next` 的 `done` 分支）：

1. 确认 `.devflow/tasks/<task-id>/task.yaml` 已归档，缺失则补写（in-place 任务共用一份 `task.yaml`，不快照会切断追溯链）
2. `git branch -d <branch>` 删本地分支（**不删远程**）
3. `git checkout <base_ref>` 切回主分支并同步

in-place 任务没有额外 worktree 需要 remove；`worktree_removed` 直接记 true。

---

## 三、PR 创建与 host adapter 边界

### 3.1 核心原则：core 定决策，adapter 定能力

- `core/orchestrator/delivery.py` 只做**只读探测**（`gh_available` / `branch_pushed` / `remote_name` / `dirty_files` / `endpoint_has_changes`）与子状态读写，**不直接执行** `git commit/push` 或 `gh pr create`。
- 真正的写命令由**主线程用 Bash 工具执行**——每一条都能被 `redline-guard.py` 的 PreToolUse hook 审计与拦截。
- adapter 提供 host 能力探测与执行边界，不伪造能力。

### 3.2 各 host 的 PR 边界

| Host | PR 创建方式 | 能力等级 | 说明 |
|------|------------|---------|------|
| Claude Code | 主线程调用 `gh pr create`（依赖用户已 `gh auth`） | hard 可执行 | `gh` 已认证可用时直接创建；未认证时明确告知用户，不静默跳过、不伪造 PR |
| Codex CLI | **router mode**：由 host 回传 `gh_pr_url` | soft | 不伪造 hard 能力，走 host 转派/回传 |
| Cursor / Trae | 待核实 | soft | 同 Codex，标注 unverified |

**关键边界（ADR-0002 强制）：**
- Claude Code 不硬编码 `gh` 存在；`gh_available()` 失败时明确告知用户安装/认证或手动建 PR。
- Codex 严禁声称 hard PR 能力；`adapters/codex/adapter.toml` 的 `unverified_extension_points` 标注 `github.pr_create`、`git.push_branch`。
- 软约束平台的后置审计（`audit-log.py`）照常运行。

---

## 四、错误 / 恢复路径

| 场景 | 处理 |
|------|------|
| `gh` CLI 缺失或未认证 | 提示用户安装/认证；不 fallback 到伪造 PR；允许「仅 commit+push，PR 手动建」 |
| push 失败（无权限 / remote 拒绝） | 保留本地 commit，报告原因，重新三合一确认 |
| PR 创建冲突（已有同分支 PR） | 复用已有 PR，`pr.md` 记录既有 URL，不重复创建 |
| 分支未合并却用 `-d` 报错 | 改用 `-D` 前先向用户确认 |
| Codex 下 PR 回传超时/失败 | 本地 commit+push 已完成，PR 状态 pending，稍后 `/devflow next` 补 |
| 中断恢复（会话断） | 读 `task.current_phase` 续跑；`deliver_confirm` 按 `delivery.yaml` 幂等恢复，重新三合一确认 |

**恢复幂等性：** 交付各步骤都有可判定状态字段（`commit`、`pushed`、`pr_url`、`worktree_removed`、`branch_deleted`、`returned_to_main`），`/devflow next` 据此跳过已完成步骤，不重复执行。

---

## 五、模块划分

| 文件 | 职责 |
|------|------|
| `core/orchestrator/SKILL.md` | 流程契约：状态机、两个 Gate、QA/review 派发、交付与收尾 |
| `core/orchestrator/task_state.py` | TaskRecord / RepoEndpoint、task.yaml 渲染与解析、归档快照 |
| `core/orchestrator/yaml_list.py` | 公共缩进列表扫描器（`parse_list_items` / `unquote`），供 task/delivery 两 reader 共用 |
| `core/orchestrator/worktree_manager.py` | create_task（anchor 建分支、候选端点）、activate_endpoint CLI、_resolve_endpoints 配置解析 |
| `core/orchestrator/delivery.py` | 只读探测 + DELIVERY_ARTIFACT_FILES 白名单 + delivery.yaml 子状态 |
| `core/orchestrator/artifact_publish.py` | 双根归档（--root/--repo-root），GATE-DELIVERY 时 publish 一次 |
| `core/hooks/devflow_guard_common.py` | 红线/白名单/边界/危险命令判定（zero-dependency） |
| `core/hooks/redline-guard.py` | PreToolUse 拦截（Read/Write/Edit/Bash） |
| `hooks/devflow_hook.py` | Stop 续跑机制入口（只提示不拦截） |
| `commands/workflow.md` | start/fix 共用流程；`init/status/next` 各自命令 |
| `adapters/codex/*` | Codex router mode 与能力声明 |

---

## 六、关键流程时序（GATE-PLAN 批准后）

```text
plan_review 批准（方案冻结）
   │
   ▼
working：实现 → QA（devflow-verifier）→ review（devflow-reviewer）
   │  review 结论摆给用户，由用户决定修还是直接交付
   ▼
deliver_confirm（GATE-DELIVERY）
   │  1. delivery.py 只读探测（gh/upstream/dirty/endpoint_has_changes）
   │  2. 白名单过滤待提交清单
   │  3. artifact_publish publish --root … --repo-root … --task …（归档一次）
   │  4. 一次三合一确认
   ▼
执行交付：commit（白名单内）→ push → gh pr create → 写 delivery.yaml
   │
   ▼
【暂停：PR 已创建，不自动合并】
   │
   ▼
用户 merge → /devflow next（done）：补归档 → 删本地分支（不删远程）→ 切回 base_ref
   ▼
distill：踩坑记录写回 Memorant（verified）；完成汇报
```

---

## 七、验证策略

1. `pytest -q core/tests`：编排/交付/状态/hook 单测无回归（测试框架为 pytest，dev dependency）。
2. `pytest -q adapters/codex/tests`：Codex 适配无回归。
3. `python3 -c 'import tomllib; tomllib.load(open("adapters/codex/adapter.toml","rb"))'`：TOML 合法。
4. grep 校验 SKILL.md / commands / docs 的 Gate 插桩点存在。
5. 手工走查：模拟一个 feature 完整走完，确认 GATE-PLAN/GATE-DELIVERY 各一次确认、PR 创建后暂停、清理后切回 main、远程分支仍在。

---

## 八、风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 交付状态与 task 状态耦合破坏 round-trip | 中 | 独立 `delivery.yaml` 子状态，最小侵入 |
| Codex 误暴露 hard PR 能力 | 中 | ADR 强制 router mode + unverified 标注 |
| 清理误删未合并本地改动 | 高 | `-d`/`-D` 分情形确认；不删远程 |
| PR 创建后用户期望自动 merge | 低 | 「暂停不合并」为固定语义 |
| 手写 YAML 解析器升级回退 | 中 | 改解析必须对照 main 基线做兼容性矩阵（PR #31/#35 教训） |

---

## 历史演进

- **v1（2026-08）**：9 阶段流水线 + 角色 Agent 分工 + 分阶段 Stop 拦截；后来者隔离到 `.devflow-worktrees/`；`context.json` 运行时状态。交付闭环以「Delivery Lifecycle 技术方案」形式设计（本文件前身）。
- **v2（2026-10-20，ADR-0005）**：编排校准——主线程直接实现，唯一 subagent 为 verifier；状态机收敛为 6 值；hook 只提示不拦截；scope.yaml/context.json 退役；后来者 worktree 隔离退役（2.2.0）。
- **v3（2026-11-18，ADR-0006）**：PRD 与方案卡合并为 `plan.md`，`prd_review` 退役（5 值）；新增 reviewer（只审不改、不阻塞）；start/fix 合并为 `workflow.md`。
- **2026-11-25/26**：多仓延迟建子仓分支（activated 候选端点）、零 diff 端点跳过 PR、workspaces `path:` 别名、公共缩进扫描器、本文现代化与 pytest 迁移。