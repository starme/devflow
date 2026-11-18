# ADR-0006：减负校准——合并需求侧 Gate、自然语言入口、review 环节

- 状态：**提议中（Proposed）**——2026-11-18
- 关联：ADR-0005（编排层校准，本 ADR 是它的续篇）、ADR-0004（归档收敛，不受影响）
- 前置：P0（红线修复）+ P1（双召回）已完成，202 个测试全绿

## 背景

ADR-0005 把 DevFlow 从「多 Agent 编排」退到「意图锚定 + 验证守门」，方向是对的。但 dogfood 之后暴露了三类新问题，它们都不是 ADR-0005 的遗留缺陷，而是**流程本身没有对齐最初的产品目标**。

最初的目标（用户原话归纳）：

> 让开发变得更简单、更能自控、能自我进化；能自我分析需求给出成熟的技术方案；过程文档留存；完成后有 QA 有 review。

对照现状：

| 原始目标 | 现状问题 |
|---|---|
| 更简单 | 入口需显式执行 `/devflow start`；进入后需加载约 250 行流程契约；4 个 Gate 无条件等人 |
| 能自控 | 状态靠模型自述（`current_phase` 只提示不拦截）；**「不扩散」在流程里没有任何一句约束** |
| 成熟技术方案 | 方案卡是模板填空，没有「备选方案 / 否决理由 / 取舍」——而这正是「成熟」的可判定标准 |
| 完成后有 QA 有 **review** | 只有 QA（`devflow-verifier` 跑验收标准），**review 完全缺失** |

同时 P1 已经给流程加了 77 行（SKILL 从 157 → 208 行）。如果不在本轮做减法，DevFlow 会退化回 v1 那种「越补越重」的形态。

## 决策

### D1：PRD 与方案卡合并为「方案文档」，`prd_review` 退役

**删除**独立的 PRD 产物与 GATE-1。

- 单一产物 `.devflow/plan.md`：原话冻结 + 需求明细（带来源标注）+ 核心诉求 + **备选方案与否决理由** + 实现要点 / 影响范围 / 风险 + 验收标准表。
- **单一 Gate（GATE-PLAN）**：整份方案文档一次审查，批准即冻结。
- `task.current_phase` 从 6 值收敛为 **5 值**：
  `qa → plan_review → working → deliver_confirm → done`
- `prd_review` 退役。hook 解析到旧值 `prd_review` 时就近映射为 `plan_review`（与 ADR-0005 处理 legacy phase 的 best-effort 策略一致）。
- `core/templates/prd.md` 保留为 `plan.md` 的**语义来源**，但不再单独输出；归档白名单里的 `.devflow/prd.md` 保留，供旧任务兼容。

**理由**：PRD 和方案卡分开审查时，人在 GATE-1 看的是「要不要做」，在 GATE-2 看的是「怎么做」——但这两件事在真实现场几乎总是一起决定的（用户看到方案才会说「那这个需求其实不用做」）。两次审查只换来一次额外的上下文重建。

**否决的替代**：保留 PRD 但把 GATE-1 改成「非阻塞通知」——那样 PRD 会变成一份没人读的产物，比删掉更糟。

### D2：锚定协议从「多轮追问」降为「一次复述确认」

**删除**填空式提问规则的强制部分，保留：

- 原话逐字冻结（不可省——这是漂移的唯一锚点）
- 第一轮核心诉求复述确认（不可省——错位在十秒内修正）
- `[推断]` 条目显式确认（不可省——这是防止模型种需求）

**删除**：

- 「每轮 Q&A 更新并展示 running summary」——这是一次复述确认的冗余版本
- 「GATE-1 只展示超出原话的条目清单」随 GATE-1 一并退役，改为方案文档中「需求明细」的来源列

**理由**：原话 + 一次复述 + 推断标注，已经覆盖三个漂移根因。多轮 running summary 是为「PRD 定稿晚、漂移烤熟才被发现」设计的，而合并后定稿提前了一整个 Gate。

### D3：`working` 阶段加入「不扩散」纪律

新增一条强制纪律（这是「能自控」的核心，此前完全缺失）：

> 实现中发现方案之外的问题 → **写进方案文档的「待办支线」一节，不改**。主线完成后统一报告给用户。

**理由**：模型看到能顺手修的东西就会修，这是 `Surgical` 原则在流程契约里的漏点。它不是能力问题，是缺一条明确禁止。

「不偏离」由方案冻结 + 偏差记录保证（已有）；「自主推进」由 Gate 减到 2 个保证（D1 + 已有设计）。

### D4：自然语言入口（关键词粗筛 + 模型判断 + 一次确认）

在 `UserPromptSubmit` hook 中新增意图识别层：

```
用户输入
  → 关键词粗筛（开发/实现/功能/修/bug/报错/重构…）
      ├─ 未命中 → 静默放行（不干预普通对话）
      └─ 命中 → 模型判断意图（start / fix / 都不是）
                  └─ start/fix → 注入「确认提示」，等用户点头后才进入流程
```

- **粗筛为的是成本**：`UserPromptSubmit` 每次输入都触发，全量模型判断会让闲聊也付费。
- **确认环节为的是误判**：识别错了直接进入流程的代价远高于多问一句。
- 已有活动 task 时，意图识别让位于「继续当前 task」，不做新任务识别。
- 识别逻辑**不改动 hook 的输出契约**（仍是 `additionalContext` 注入），失败一律静默放行（沿用现有 fail-open）。

**否决的替代**：纯模型判断（每次输入都判断）——成本不可控；纯关键词（不判断）——误报率高，把「这个 bug 怎么修」当成交付任务。

### D5：新增 `devflow-reviewer` Agent，产出报告后由用户决定是否修复

新增第二个（也是唯一新增的）subagent，与 `devflow-verifier` 分工明确：

| | `devflow-verifier`（QA） | `devflow-reviewer`（Review） |
|---|---|---|
| 判定依据 | 方案文档的验收标准（A1/A2…） | 代码规范 / 安全 / 质量，**无预设清单** |
| 证据要求 | 每条附命令输出或文件行号 | 每条附文件行号与具体代码 |
| 是否修改 | 不改 | 不改 |
| 产出 | `.devflow/verification-report.md` | `.devflow/review-report.md` |
| 失败处理 | 主线程自己修，3 轮上限 | **报告交用户，由用户决定是否修复** |

- **review 不是 Gate，不阻塞流程**。它把材料摆到交付确认面前，修不修由用户定。
- review 维度（代码规范 / 安全审计 / 质量）在 Agent 定义里写死，复用项目已有的 lint / 安全审查能力，不引入新依赖。
- 两个 Agent 都在 `deliver_confirm` 之前完成；`review-report.md` 列入归档白名单与交付白名单。

**理由**：写代码的模型不能审自己的代码，这是 review 存在的全部意义。把 review 塞进 verifier 会让它既测不准也不专注。

**代价**：新增一个 Agent 定义（约 50 行）+ 一个报告产物 + 白名单条目两条。这是本 ADR 唯一增加重量的决策，换来的是原始目标里明确要求、目前完全缺失的能力。

### D6：`fix.md` 与 `start.md` 合并为 `devflow.md` 的单一路径分支

当前两个命令文件的重复内容超过 60%（前置检查、创建 task、交付、清扫）。合并为同一命令的 feature / fix 两条路径说明。

- `/devflow fix` 作为兼容别名保留（不破坏既有用户肌肉记忆），内部走同一份契约。
- `commands/` 从 6 个文件降到 5 个。

## 减重/增重账（预计）

| 项 | 变化 | 说明 |
|---|---|---|
| `SKILL.md` | 208 → **≤130 行** | D1 删 Gate-1 段 + D2 删多轮追问 + D3 增 3 行 |
| `commands/start.md` + `fix.md` | 94 行 → 约 **50 行** | D6 合并 |
| `core/templates/prd.md` | 保留但不再输出 | D1 |
| 新增 `plan.md` 模板 | +60 行 | D1（替代 prd.md + task-card.md 的合并体） |
| 新增 `reviewer-agent.md` | +50 行 | D5 |
| `task.current_phase` | 6 值 → 5 值 | D1 |
| hook 意图识别 | +40 行代码 | D4 |

**净效果**：提示词总量下降约 30%，人等待点从 4 个降到 2 个，能力上新增 review 与自然语言入口。

## 影响清单（必须同步的消费者）

| 文件 | 改动 |
|---|---|
| `core/orchestrator/SKILL.md` | 重写状态机、锚定协议、方案文档、working 纪律、review 环节 |
| `core/orchestrator/task_state.py` | `render_task_yaml` 的 phase 文档字符串从 6 值改 5 值（不校验值，纯注释） |
| `core/templates/task-card.md` → `plan.md` | 合并 PRD 与方案卡模板 |
| `core/templates/prd.md` | 标注为「被 plan.md 取代，保留供旧任务」 |
| `commands/start.md` / `fix.md` | 合并或瘦身 |
| `commands/next.md` / `status.md` | 删 `prd_review` 行，加「待办支线」「review 报告」 |
| `hooks/devflow_hook.py` | 加意图识别；`gate_phases` 集合删 `prd_review` 加映射 |
| `agents/reviewer-agent.md` | 新增 |
| `core/orchestrator/delivery.py` | 白名单加 `.devflow/plan.md`、`.devflow/review-report.md` |
| `core/hooks/devflow_guard_common.py` | `_DEVFLOW_ARTIFACT_FILES` 同步 |
| `core/tests/test_task_state.py` | phase 集合断言改 5 值 |
| `core/tests/test_devflow_hook.py` | `prd_review` 用例改映射断言 |
| `docs/workflow.md` / `docs/architecture.md` | 状态机图与人工介入点 |
| `README.md` / `README.zh-CN.md` | 流程概览图 |
| `.claude-plugin/plugin.json` 等三份 manifest | 版本 2.0.0 → **2.1.0**（破坏性 phase 变更 + 新增 Agent） |

## 后果

- 用户等待点：4 → 2（GATE-PLAN 方案冻结、GATE-DELIVERY 交付确认）
- `prd_review` 从状态机消失，旧 task 就近映射，不报错
- review 成为交付前的固定材料，但**不阻塞**
- 自然语言入口降低启动摩擦，但每次输入多一次关键词匹配（哈希级，可忽略）
- 与 ADR-0005 的「hook 永不拦截」原则一致：意图识别只注入上下文，不 block
- **风险**：合并 Gate 后，用户可能在新方案文档里一次面对更多决定。缓解：方案文档强制把「需求明细」和「方案要点」分段，审查时可按段展示

## 验证

本 ADR 的落地任务即新的 dogfood。验收标准：

1. `python3 -m unittest discover -s core/tests` 全绿（含新增 review / 意图识别 / 5 值状态机用例）
2. `SKILL.md` 行数 ≤ 130
3. `grep -r prd_review` 在代码路径中只剩兼容映射与测试断言
4. 手工走一次 feature：自然语言入口 → 确认 → 方案文档 → GATE-PLAN → 实现 → QA → review → GATE-DELIVERY

## 未决

- 无。P3 落地时若发现与本 ADR 冲突的既有契约，回到本 ADR 补充修订记录，不改正文决策。
