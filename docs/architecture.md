# 交付生命周期（Delivery Lifecycle）技术方案

## 背景与目标

当前 DevFlow 在「验收签字 → 完成」之间缺少自动化的交付闭环。用户痛点（来自本 feature 的 task 描述）：

1. 研发阶段虽然 `worktree_manager.create_task` 已自动创建 `feature/<slug>-<id>` 分支和 task worktree，但研发 Agent 在 task worktree 内的改动**没有被 commit**，改动散落在工作区。
2. 验收人工签字后，没有自动执行「提交 commit + 推送分支 + 创建 PR + 清理 worktree」，需要一次次手动强调。
3. 交付完成后没有切回主分支。

本方案目标：在状态机中新增 **DELIVERY 阶段**与 **GATE_DELIVERY 用户确认点**，把「提交/推送/PR/清理/返回主仓库」收敛为一次性的确定流程，并明确 PR 创建与 host adapter 的边界。

---

## 一、状态机新阶段与字段

### 1.1 新阶段

在 `ACCEPTANCE` 与 `DISTILL` 之间插入 `DELIVERY`，内含一个 `GATE_DELIVERY` 确认点：

```text
... → ACCEPTANCE → DELIVERY(含 GATE_DELIVERY) → DISTILL → DONE
```

- `DELIVERY` 是**自动阶段**（进入 `auto_phases`，Stop hook 阻止并提示继续）。
- `GATE_DELIVERY` 是**用户确认点**（进入 `gate_phases`）。

### 1.2 用户确认点（三合一，一次询问）

验收签字后，Manager **一次性**向用户列出：

1. 待提交文件清单（经白名单过滤后的 `git status --porcelain`）
2. 目标分支 `feature/<slug>-<id>`
3. remote 名称与 push 目标
4. PR 标题 / 描述预览

并询问一次：**「是否执行：提交 commit + 推送分支 + 创建 PR？」**

- 用户仅回复「通过 / 同意 / 签字」→ 默认**三者全执行**。
- 用户有其他意见（如「先只提交不 push」「PR 标题改成…」）→ 按需调整，不擅自决定。
- 用户在签字的同时未提出异议 → 视为同意三合一默认。

### 1.3 新状态字段

**`task.yaml`（由 `core/orchestrator/task_state.py` 的 `render_task_yaml` 扩展）新增 `delivery` 段：**

```yaml
delivery:
  commit: null          # 交付 commit 的 short hash
  pushed: false         # 分支是否已 push 到 remote
  remote: "origin"      # remote 名称
  pr_url: null          # PR URL（未创建为 null）
  pr_title: null        # PR 标题
  worktree_removed: false  # 本地 task worktree 是否已清理
  branch_deleted: false    # 本地分支是否已删除
  returned_to_main: false  # 是否已切回 base_ref 主分支
```

**`context.json`（`core/templates/context.json`）新增 `delivery` 上下文块：**

```json
"delivery": {
  "gh_available": "{{GH_AVAILABLE}}",
  "branch_pushed": "{{BRANCH_PUSHED}}",
  "pr_url": "{{PR_URL}}"
}
```

> 注意：`task_state.py` 当前 `TaskRecord` 是 `frozen dataclass` 且 `load_task` 只解析标量字段。扩展 `delivery` 段时需要同步扩展 `TaskRecord` 字段与 `_read_scalar` 的解析，或采用独立的 `delivery.yaml` 子状态文件，避免破坏现有 round-trip 测试（`test_worktree_manager.py`）。**推荐方案：新增独立 `.devflow/delivery.yaml` 作为交付子状态**，与 `task.yaml` 解耦，`task.yaml` 仅在 `artifacts` 段加一个 `delivery: ".devflow/delivery.yaml"` 引用——最小侵入，不破坏 `TaskRecord` 结构。

---

## 二、交付流程（Manager 执行）

### 2.1 commit 文件白名单

提交前用白名单过滤 `git status --porcelain`：

**允许提交（ADD）：**
1. 所有已跟踪文件的改动（`M` / `A` / `D`）
2. `docs/**` 下已跟踪的文档（`docs/architecture.md`、`docs/workflow.md`、`docs/adr/*.md`、`README*.md`）
3. `.devflow/**` 中在 `DELIVERY_ARTIFACT_FILES` 白名单内的产物

**禁止提交（SKIP）：**
- 临时文件、编辑器残留、`*.tmp`、`*.log`
- `.devflow/context.json`（运行时上下文，属 `_NEVER_COLLECT`）
- `.devflow/runs/**`（审计日志，不进交付）
- 未跟踪且不在 `.devflow` 白名单内的文件

**`DELIVERY_ARTIFACT_FILES` 白名单（与 `devflow_guard_common._DEVFLOW_ARTIFACT_FILES` 并集对齐）：**

```text
.devflow/scope.yaml
.devflow/prd.md
.devflow/architecture.md
.devflow/diagnosis.md
.devflow/acceptance-report.md
.devflow/acceptance-scenarios.md
.devflow/test-report.md
.devflow/pr.md            # 新增：PR 创建结果记录
.devflow/delivery.yaml    # 新增：交付子状态
```

### 2.2 commit 规范

- 遵循 Conventional Commits：`feat: ...` / `fix: ...` / `chore: ...`，imperative mood。
- 由 Manager 汇总本次改动生成 commit message，不照搬 task 描述原文，避免超长。
- 例：`feat: add delivery lifecycle (commit/push/PR/cleanup)`。

### 2.3 push 与 PR 创建

- push：`git push -u origin <branch>`（首次）；已存在上游则 `git push origin <branch>`。
- PR 创建成功后写 `.devflow/pr.md`（含 PR URL、标题、base/head 分支、时间戳）。
- **PR 创建后暂停，不自动合并**。

### 2.4 清理与返回主仓库（PR 合并后 / 交付闭环）

PR 创建后**不自动清理**——清理发生在 PR 合并、交付闭环确认时：

1. `git worktree remove <worktree> --force` 删除本地 task worktree
2. `git branch -d <branch>` 删除本地分支（仅在分支已合并时 `-d`；未合并需 `-D`，先向用户确认）
3. **不删除远程分支**（remote branch 由 PR 合并后的平台策略决定，DevFlow 不越权删除）
4. `git checkout <base_ref>` 切回主分支（`base_ref` 固化在 `task.yaml` 的 `git.base_ref`）

---

## 三、PR 创建与 host adapter 边界

### 3.1 核心原则：core 定决策，adapter 定能力

- `core/orchestrator/delivery.py` 只做**只读探测**（`gh_available` / `branch_pushed` / `remote_name` / `dirty_files`）与决策逻辑，**不直接执行** `git commit/push` 或 `gh pr create` 写命令。
- 真正的 `git commit` / `git push` / `gh pr create` 由 **Manager 在 task worktree 内用 Bash 工具执行**——这样每一条写命令都能被 `redline-guard.py` 的 PreToolUse hook 审计与拦截。
- adapter 提供 **host 能力探测与执行边界**，不伪造能力。

### 3.2 各 host 的 PR 边界

| Host | PR 创建方式 | 能力等级 | 说明 |
|------|------------|---------|------|
| Claude Code | Manager 调用 `gh pr create`（依赖用户已 `gh auth`） | hard 可执行 | `gh` 已认证可用时直接创建；未认证时降级为引导用户手动创建 |
| Codex CLI | **router mode**：由 host 回传 `gh_pr_url` | soft | Codex 未核实通用文件写前置 hook，PR 创建不伪造 hard 能力，走 host 转派/回传 |
| Cursor / Trae | 待核实 | soft | 同 Codex，标注 unverified |

**关键边界（ADR-0002 强制）：**
- Claude Code 不硬编码 `gh` 存在；`gh_available()` 探测失败时，Manager 明确告知用户「未检测到 gh CLI 或未认证，请安装/认证后重试，或手动创建 PR」，不静默跳过。
- Codex 严禁声称 hard PR 能力；`adapters/codex/adapter.toml` 的 `unverified_extension_points` 标注 `github.pr_create`、`git.push_branch`。
- 软约束平台的后置审计（`audit-log.py`）在交付阶段照常运行。

---

## 四、错误 / 恢复路径

| 场景 | 处理 |
|------|------|
| `gh` CLI 缺失或未认证（Claude Code） | 提示用户安装/认证；不自动 fallback 到伪造 PR；允许用户改为「仅 commit+push，PR 我手动建」 |
| push 失败（无权限 / remote 拒绝） | 保留本地 commit，报告用户 push 失败原因，进入 GATE_DELIVERY 重新确认；不清理 worktree |
| PR 创建冲突（已有同分支 PR） | 复用已有 PR，`pr.md` 记录既有 URL，不重复创建 |
| 清理时 worktree 有未提交改动 | `git worktree remove` 前先 `git status`，若有未进入白名单的改动，暂停并提示用户是否放弃或保留；不强制 `--force` 丢改动 |
| 分支未合并却用 `-d` 报错 | 改用 `-D` 前先向用户确认「分支未合并，是否强制删除本地分支？」 |
| Codex 下 PR 回传超时/失败 | 本地 commit+push 已完成，PR 状态记为 pending，用户可稍后 `/devflow next` 补 PR；不阻塞清理 |
| 中断恢复（会话断） | `delivery` 在 `auto_phases`，Stop hook 阻止并提示 `/devflow next`；`gate_delivery` 在 `gate_phases`，重新提示三合一确认 |

**恢复幂等性：** 交付各步骤（commit / push / PR / 清理）都有可判定的状态字段（`commit`、`pushed`、`pr_url`、`worktree_removed`、`branch_deleted`、`returned_to_main`），`/devflow next` 依据这些字段跳过已完成步骤，不重复执行。

---

## 五、模块划分与改动文件

### 新增

| 文件 | 职责 |
|------|------|
| `core/orchestrator/delivery.py` | 交付编排：只读探测（gh/branch/remote/dirty）+ `DELIVERY_ARTIFACT_FILES` 白名单 + 交付子状态读写 |
| `core/tests/test_delivery.py` | delivery.py 单测 + 白名单一致性测试 |

### 修改

| 文件 | 改动点 |
|------|--------|
| `core/orchestrator/SKILL.md` | 状态机图插 DELIVERY + 阶段 9.5 交付闭环 + DONE 清理/返回主仓库 + 中断恢复 |
| `core/orchestrator/task_state.py` | `artifacts` 段加 `delivery` 引用（或独立 delivery.yaml 解析） |
| `core/templates/context.json` | 新增 `delivery` 上下文块 |
| `core/hooks/devflow_guard_common.py` | `_DEVFLOW_ARTIFACT_FILES` 补 `.devflow/pr.md`、`.devflow/delivery.yaml` |
| `hooks/devflow_hook.py` | `auto_phases` + `delivery`，`gate_phases` + `gate_delivery` |
| `commands/start.md` / `next.md` / `status.md` / `fix.md` | 阶段序列与恢复表接入 DELIVERY |
| `docs/workflow.md` | 状态机口诀 / 流程图 / 人类介入点（4→5）/ 裁剪表补 DELIVERY |
| `docs/adr/0002-delivery-lifecycle.md` | 交付生命周期 ADR |
| `README.md` / `README.zh-CN.md` | 一句话交付闭环说明 |
| `adapters/codex/adapter.toml` / `AGENTS.md` / `devflow-codex.md` | Codex delivery 能力声明 |

---

## 六、关键流程时序（验收签字后）

```text
ACCEPTANCE 通过（用户签字）
   │
   ▼
DELIVERY（自动阶段）
   │  1. delivery.py 探测：gh 可用？分支已 push？working tree 状态？
   │  2. 白名单过滤 git status，生成待提交清单
   │  3. 生成 commit message + PR 标题/描述预览
   │
   ▼
GATE_DELIVERY（用户确认点）——一次询问「commit + push + PR」
   │  用户签字 → 三合一默认执行
   │  用户有意见 → 按需调整
   │
   ▼
执行交付：
   │  1. git commit（白名单内文件）
   │  2. git push -u origin <branch>
   │  3. gh pr create（Claude Code）/ host 回传（Codex）→ 写 .devflow/pr.md
   │
   ▼
【暂停：PR 已创建，不自动合并，等待 review/merge】
   │
   ▼
DISTILL → DONE
   │  交付闭环：清理本地 worktree + 本地分支（不删远程）+ 切回 base_ref 主分支
   ▼
完成汇报（commit / PR URL / 清理状态 / 当前分支）
```

---

## 七、验证策略

1. `python3 -m unittest discover -s core/tests -v`：delivery.py 单测 + 既有测试无回归。
2. `python3 -m unittest discover -s adapters/codex/tests -v`：Codex 适配无回归。
3. `python3 -c 'import tomllib; tomllib.load(open("adapters/codex/adapter.toml","rb"))'`：TOML 合法。
4. grep 校验 SKILL.md / commands / docs 的 DELIVERY 插桩点存在。
5. 手工走查：模拟一个 feature 完整走完，确认验收签字后出现 GATE_DELIVERY 一次确认、PR 创建后暂停、清理后切回 main、远程分支仍在。

---

## 八、风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `task_state.py` 扩展破坏 round-trip 测试 | 中 | 采用独立 `.devflow/delivery.yaml` 子状态，最小侵入 |
| Codex 误暴露 hard PR 能力 | 中 | ADR 强制 router mode + unverified 标注 |
| 清理误删未合并本地改动 | 高 | 清理前 `git status` 校验 + `-d`/`-D` 分情形确认 |
| PR 创建后用户期望自动 merge | 低 | 明确「暂停不合并」为固定语义，用户手动 review/merge |
| 交付阶段 hook 漏审计写命令 | 中 | 强制 Manager 用 Bash 执行写命令，delivery.py 只探测不写 |
