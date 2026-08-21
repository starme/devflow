# ADR-0002：验收签字后的交付生命周期（Delivery Lifecycle）

## 状态

已提议（Proposed）——本 ADR 与 `docs/architecture.md` 一并作为功能方案冻结，待 GATE_ARCH 审批后落地。

## 背景

现有 DevFlow 阶段状态机终点是 `ACCEPTANCE → DISTILL → DONE`。用户反馈三个不顺畅点：

1. 研发阶段虽已由 `worktree_manager.create_task` 创建了 `feature/<slug>-<id>` 分支和 task worktree，但研发 Agent 在 worktree 内的改动未被 commit。
2. 验收人工签字后，没有自动执行「提交 commit + 推送分支 + 创建 PR + 清理 worktree」，需要一次次手动强调。
3. 交付完成后没有切回主分支。

这些操作每次都要人工反复提醒，违背 DevFlow「人类只在决策点介入，其余自动执行」的核心原则。

## 决策

在状态机 `ACCEPTANCE` 与 `DISTILL` 之间新增 **`DELIVERY` 阶段**，内含一个 **`GATE_DELIVERY` 用户确认点**：

1. **三合一一次确认**：验收签字后，Manager 一次性列出「待提交文件清单（白名单过滤后）+ 分支 + 目标 remote + PR 标题/描述预览」，询问一次「是否执行：提交 commit + 推送分支 + 创建 PR」。用户仅回复「通过 / 同意 / 签字」即默认三者全执行；有其他意见按需调整。
2. **PR 创建后暂停，不自动合并**：DevFlow 不越权合并；合并是用户的 review 决策。
3. **交付闭环清理**（PR 合并后）：`git worktree remove` 删除本地 task worktree + `git branch -d` 删除本地分支 + `git checkout <base_ref>` 切回主分支。**不删除远程分支**。
4. **commit 文件白名单**：已跟踪改动 + `docs/**`（已跟踪）+ `.devflow/**` 白名单产物；排除临时文件、`context.json`、`runs/`。
5. **Commit 规范**：Conventional Commits，imperative mood，Manager 汇总生成。

### PR 创建与 host adapter 边界

- **core 定决策，adapter 定能力**：`core/orchestrator/delivery.py` 只做只读探测，Manager 用 Bash 工具执行 `git commit/push` 与 `gh pr create`（确保被 PreToolUse hook 审计）。
- Claude Code：`gh pr create`（依赖用户已认证），探测失败则引导用户手动创建，不静默跳过。
- Codex CLI：`router` mode，由 host 回传 `gh_pr_url`，**不伪造 hard PR 能力**；`adapters/codex/adapter.toml` 将 `github.pr_create`、`git.push_branch` 标注为 unverified。

## 理由

- 把「提交/推送/PR/清理」收敛为一次确认，把人类介入从「反复提醒」降为「一个决策点」，契合「人类只在决策点介入」原则。
- 交付闭环放在 `DISTILL` 之前，经验蒸馏时仓库/分支状态已稳定、可回溯。
- 只读探测与写命令执行分离，保证 hook 能审计到每一次 git 写操作，不削弱红线防护。
- 白名单显式列明，避免把临时文件、审计日志、运行时上下文误提交进 PR。

## 否决的替代方案

- **在 ACCEPTANCE 阶段内部直接 commit/push，不单设阶段**：把两个性质不同的活动（验收 vs 交付）混在一个阶段，中断恢复与 Stop hook 的 auto/gate 判断会变复杂，且无法给用户一个清晰的「交付确认」决策点。
- **自动合并 PR（pr 创建后直接 merge）**：越权替用户做合并决策，违背 review 流程，一旦误合并不可逆。
- **交付完后删除远程分支**：远程分支生命周期由平台 PR 合并策略决定，DevFlow 删除会与代码托管平台的合并/保护规则冲突。
- **Codex 伪装 hard PR 能力**：Codex 官方文档未确认通用文件写入前置 hook，伪造 hard 会给出虚假安全感，违背适配契约「宁可降级也不伪造」。

## 适用条件

- 所有 `work_type`（feature / bugfix / chore）都走 DELIVERY 交付闭环；feature 在 ACCEPTANCE 签字后，bugfix/chore 在回归确认通过后。
- legacy manifest 项目通过兼容路径同样适用（交付阶段从 task.yaml / delivery.yaml 读状态）。
- 无 `gh` CLI 或平台不支持 PR 时，降级为「commit + push + 引导用户手动 PR」，不阻塞交付闭环其余部分。
