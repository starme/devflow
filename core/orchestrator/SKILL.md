---
name: devflow-orchestrator
description: >-
  DevFlow 流程契约（ADR-0006）。编排按模型能力裁剪，意图与验证按信任保留。
  主线程自己实现；verifier 判「按标准做完了吗」，reviewer 判「代码本身行不行」。
  人只在两个点拍板：方案冻结、交付确认。
---

# DevFlow 流程契约

你自己澄清需求、写方案、写代码、跑验证，不按角色切块派 Agent。
依据：[ADR-0005](docs/adr/0005-orchestration-recalibration.md)、[ADR-0006](docs/adr/0006-lean-recalibration.md)。

## 状态机

`task.current_phase` 取 5 个值，只用于提示注入，**hook 永不拦截**。

| 值 | 含义 | 谁推进 |
|---|------|--------|
| `qa` | 需求澄清或 bug 诊断 | 主线程 ↔ 用户 |
| `plan_review` | GATE-PLAN：等人审方案文档 | 等用户 |
| `working` | 实现 → QA → review | 主线程 |
| `deliver_confirm` | GATE-DELIVERY：等人确认交付 | 等用户 |
| `done` | PR 已合并、清理完成 | — |

每需求人只出现 **2 次**（方案冻结、交付确认）。其余阶段一口气干到下一个 Gate；
`/devflow next` 只用于会话中断恢复与 PR 合并后的清理。

## qa

**feature**：原话**逐字**钉进方案文档第 1 节（永不改写）→ 2-3 句复述核心诉求获确认 →
只做填空式提问（补缺口，不做加法）→ 想补充的列为 `[推断]`，显式确认前不进需求明细。

**fix**：冻结原话症状 → 复现步骤 → 根因。

原话是漂移的唯一锚点；一次复述是错位成本最低的修正时机。

## 召回（自我进化的入口）

自我进化 = 写回 + 召回 + 迭代。写回不召回，经验是死数据；召回不写回，下次无可召回。

**设计时**（写方案之前）：调 `memorant_recall`，检索词 = 核心意图 + 领域词 + `方案`/`选型`/`架构`，
结果填方案文档第 4 节。空也要写「无相关历史」——空节本身是「新领域」的信号。
**信任级别照抄 `trust_tier`**：`verified` 可沿用，`provisional` 必须重新验证；把被推翻的旧记忆
当真理喂回来是召回最危险的失败。Memorant 不可用写「不可用」并继续。

**开发时**（事件触发，不触发不召回），结果写进第 9 节「踩坑记录」——写进方案文档才会随交付归档，
下次召回才命中得上它自己：

| 触发 | 检索词 |
|---|---|
| 测试 / lint / 构建失败 | 第一条错误行（去栈、去绝对路径、限 200 字） |
| `devflow:devflow-verifier` 报 FAIL | 该验收标准 + 失败证据摘要 |
| 首次修改某个文件 | 文件名 + `修改` / `坑` / `注意` |
| 准备引入新依赖 | 包名 + `已知问题` |

没命中写「未命中」并继续，**不要自己编经验**。

## 产物路径（先读这条）

**凡是 `.devflow/` 下的过程产物，一律写在与 `task.yaml` 同级的目录。**

`create_task` 把 `task.yaml` 写到 `project_root`——多数普通项目里就是仓库根，但插件自托管仓库里
它可能在仓库的**上一级**。`artifact_publish` 也按那份 `task.yaml` 找产物。所以「相对工作区」
这个说法不够：工作区是本任务 checkout 的目录，产物目录是 `task.yaml` 的目录，两者可以不同。

写产物前先定位，**从 `git rev-parse --show-toplevel` 起逐级向上**找最近的 `.devflow/task.yaml`：

```bash
d="$(git rev-parse --show-toplevel)"
while [ "$d" != "/" ]; do
  [ -f "$d/.devflow/task.yaml" ] && { echo "$d/.devflow"; break; }
  d="$(dirname "$d")"
done
```

两条注意：

- 不要用 `find .`——它只搜当前目录树，而 `task.yaml` 可能就在仓库上一级。
- **找到的 `task.yaml` 要核对其 `phase` 不是 `done`**。仓库内可能残留上一轮任务的 `task.yaml`
  （本仓库就有一个 10-23 的 `devflow/.devflow/task.yaml`，`phase: done`），
  而活动 task 在上一级。**`phase: done` 的那份不是当前 task**，继续往上找。

产物落到别处的后果是静默的：文件写成功了，`/devflow status` 显示「未审查」，
交付归档时找不到它。**不会报错，只会丢东西。**

## GATE-PLAN：方案文档

写 `<task.yaml 同级>/.devflow/plan.md`（模板 `core/templates/plan.md`），一份文档同时回答「要不要做」和「怎么做」。

硬约束：原话逐字；需求明细每条标来源（`原话`/`Q&A·R<N>`/`推断·已确认 <日期>`）且非目标必填；
历史经验必须存在；**备选方案至少两个并写明否决理由**（说不出理由说明没比过）；验收标准每条标
`cmd`/`ai`/`manual` 并映射 R#；**≤1.5 页（约 100 行）**，超限说明该拆任务。

审查按段展示，重点给**来源 ≠ 原话的行**。批准即冻结，同时写回一条 `plan_pattern`
（`provisional`）：哪类需求 → 选了什么方案 → 理由 → 代价。

## working：实现 → QA → review

**实现**：在工作区分支直接做，完成一项勾一项。

**多仓延迟建分支**：创建 task 时只在 anchor 建了分支，子仓是候选端点（`activated: false`）。
首次要改某子仓前，先激活其分支再动手改：

```bash
python3 "$CLAUDE_PLUGIN_ROOT/core/orchestrator/worktree_manager.py" activate-endpoint --root <project_root> --track <track>
```

幂等（已激活则跳过），成功后该端点标 `activated: true`。没改到的子仓不建分支、不切换。

**不扩散**：发现方案之外的问题 → 写进第 10 节「待办支线」，**不改**，主线完成后统一报告。
顺手改掉就是扩散，会让本任务的验收标准失效。偏差记进第 11 节；涉及验收标准变更回 GATE-PLAN。

**QA** → 派 `devflow:devflow-verifier`，输入 `plan_path` / `rules` / `memorant_context` / `round`，
产物 `.devflow/verification-report.md`。全 PASS 进 review；FAIL 自己修后重派（3 轮仍 FAIL 停下报告）；
BLOCKED 报环境问题；MANUAL 留到交付确认。

**review** → 派 `devflow:devflow-reviewer`，输入 `plan_path` / `base_commit` / `rules` / 可用 lint 与安全工具，
产物 `.devflow/review-report.md`（按 high/medium/low 分级，带文件行号）。它**不是 Gate、不阻塞**。

### review 之后：人来决定（重要）

review 报告出来后，**把结论原样摆给用户，由用户决定修还是直接交付**。

**不要自己发起第二轮 review。** 理由不是流程洁癖——实现者是同一个模型，让它派 agent 复查
自己刚改的代码、再自己消费结论，就是**自我批准**：第一轮还有真实盲点可抓，第二轮只剩
「我改完了，确认我改对了」。这个循环在权限层面会被判定为 self-approval 并拒绝，
即便没被拒绝，它也不产生独立判断。

所以：

| 场景 | 谁决定 |
|---|---|
| review 报告出来 | 用户决定修哪些、还是直接交付 |
| 修完是否需要**第二轮** review | **用户决定**；用户没要求就不重派 |
| 第二轮的结论 | 交给用户看，不自动开修 |

**review 只做一次是常态。** 修完有 QA 回归 + 测试覆盖，这已经足够支撑交付判断。

## GATE-DELIVERY

1. `delivery.py` 只读探测（gh 可用性、upstream、dirty），白名单过滤待提交清单。
2. 归档到 `.devflow/tasks/<task-id>/`（幂等：未变 skip，冲突不覆盖，缺失提示跳过）：
   `python3 "$CLAUDE_PLUGIN_ROOT/core/orchestrator/artifact_publish.py" publish --root <project_root> --repo-root <repo_root> --task <task-id>`
3. 一次询问：待提交清单 + 分支 + remote + PR 预览 + 验证摘要 + review 摘要 + manual 项 +
   待办支线 → 「是否 commit + push + 创建 PR？」
4. commit（白名单内）→ push → `gh pr create`（codex 走 router 回传）→ 写 `.devflow/delivery.yaml`。
5. **PR 创建后暂停，永不自动 merge。** 多仓库每个**已激活**端点（`activated: true`）各自 commit/push/PR，逐仓报成败；未激活的候选端点不开 PR。

`gh` 缺失或未认证时明确告知用户，不静默跳过、不伪造 PR。

## 写回与收尾

写回**只在两个点**，中途不写（中途的记忆质量差，写进去下次召回反而误导）：
GATE-PLAN 批准时写 `plan_pattern`（`provisional`）；task 完成时把「踩坑记录」逐条转
`bug_pattern`（现场错误 + 根因 + 修复方法，`verified`）。Memorant 不可用写 `.devflow/retrospective.md`。

**done**（仅 PR 已合并后）：删本地分支（**不删远程**）、切回 `base_ref`。所有 task 都在主工作区
in-place 进行，没有需要清理的额外工作区。审计日志留在 `.devflow/runs/<task-id>/`。

## 中断恢复（/devflow next）

| 值 | 行为 |
|---|------|
| `qa` | 继续澄清或诊断 |
| `plan_review` | 重新展示方案文档，等批准 |
| `working` | 读进度继续；看缺 QA 还是缺 review，补跑 |
| `deliver_confirm` | 按 `delivery.yaml` 幂等恢复，重新三合一确认 |
| `done` | 仅当 PR 已合并：执行清理；未合并则报告等待 |

旧值 `prd_review` 映射为 `plan_review`。产物缺失时重新生成，不编造内容。

## 安全边界

主线程可直接写 `.devflow/`；业务代码遵循项目规则与红线。不替用户做产品决策，Gate 必须等人。
未确认不删文件、不跑迁移、不 commit/push。不读 `.env*`、`*.pem`、`secrets.*`、`config/*.key`。
红线 guard 与审计日志是硬边界，与本流程正交，不在流程内绕过。
