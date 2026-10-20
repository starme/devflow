# DevFlow 工作流程详解

> 本文件承接 README 中的流程概览，补充状态机、锚定协议、Gate 定义与 bugfix 精简路径。
> v2 校准的决策依据见 [ADR-0005](adr/0005-orchestration-recalibration.md)。

## 完整工作流程图

```mermaid
flowchart TD
    START["用户输入"]

    START --> NEW["/devflow init<br/>初始化项目"]
    NEW --> STARTFEATURE["/devflow start<br/>启动需求"]
    START --> FIX["/devflow fix<br/>修 bug / 日常维护"]

    subgraph full["功能路径（feature）"]
        QA["💡 锚定 Q&A<br/>冻结原话 · 填空式追问 · 每轮 running summary"]
        PRD["📄 PRD<br/>≤1.5 页 · 每条需求标注来源"]
        G1{{"GATE-1: PRD 漂移聚焦审查<br/>核心诉求复述 + 超出原话的条目清单"}}
        CARD["🗂️ 方案卡<br/>方案要点 · 影响范围 · 风险<br/>验收标准表（cmd/ai/manual → R#）"}}
        G2{{"GATE-2: 方案卡评审<br/>批准即方案与验收标准冻结"}}
        DEV["⚙️ 主线程实现<br/>功能分支 · 勾选进度 · 记录偏差"]
        V["🔍 devflow-verifier<br/>逐条执行验收标准 + 回归<br/>无证据不得 PASS"]
        G3{{"GATE-3: 交付三合一确认<br/>附验证报告 + manual 项<br/>commit + push + PR"}}
        DISTILL["💎 蒸馏<br/>经验写入 Memorant"]
        DONE["🎉 完成<br/>PR 合并后清理"]
    end

    subgraph fixmode["修复路径（bugfix / chore）"]
        DIAG["🔍 诊断<br/>冻结原话症状 · 复现 · 根因"]
        FCARD["🗂️ 诊断卡（方案卡瘦版）<br/>根因 · 修复方案 · 回归标准"]
        FG{{"GATE: 诊断卡评审（单 Gate）"}}
    end

    MEM["💎 Memorant<br/>召回 · 蒸馏 · 信任路由"]

    STARTFEATURE --> QA
    QA --> PRD
    PRD --> G1
    G1 -->|人批准| CARD
    G1 -->|要求修改| QA
    CARD --> G2
    G2 -->|人批准| DEV
    G2 -->|要求修改| CARD
    DEV --> V
    V -->|FAIL| DEV
    V -->|全 PASS| G3
    G3 -->|人确认| DISTILL
    G3 -->|要求调整| DEV
    DISTILL --> DONE

    FIX --> DIAG
    DIAG --> FCARD
    FCARD --> FG
    FG -->|人批准| DEV

    MEM -.->|相似需求/漂移教训| QA
    MEM -.->|相似 bug| DIAG
    MEM -.->|测试经验| V
    DISTILL -.->|写入记忆| MEM

    classDef human fill:#f0edff,stroke:#6c5ce7,stroke-width:2px,color:#1a1a2e
    classDef auto fill:#f7f7fc,stroke:#e2e2f0,stroke-width:1px,color:#1a1a2e
    classDef gate fill:#fffbf0,stroke:#fdcb6e,stroke-width:1.5px,color:#1a1a2e
    classDef verify fill:#e6fff9,stroke:#00b894,stroke-width:1.5px,color:#1a1a2e
    classDef fix fill:#fff0ed,stroke:#e17055,stroke-width:1.5px,color:#1a1a2e
    classDef memorant fill:#f0edff,stroke:#6c5ce7,stroke-width:1.5px,stroke-dasharray:5 3,color:#6c5ce7
    classDef entry fill:#e8e8f0,stroke:#4a4a68,stroke-width:2px,color:#1a1a2e

    class START,NEW,FIX entry
    class QA,G1,G2,G3,FG human
    class PRD,CARD,DEV,DISTILL,DONE auto
    class DIAG,FCARD fix
    class V verify
    class MEM memorant
```

**图例：** 紫色 = 需要人决策 ｜ 黄色 = 等待人工批准的 Gate ｜ 绿色 = 机器验证 ｜ 橙色 = 修复路径 ｜ 紫色虚线 = Memorant 记忆闭环

## 状态机

`task.yaml` 的 `task.current_phase` 只有 6 个值，只用于提示注入，**hook 永不拦截**：

```text
qa → prd_review → plan_review → working → deliver_confirm → done
```

| 值 | 含义 | 停还是干 |
|---|------|---------|
| `qa` | 需求澄清（锚定协议）或 bug 诊断 | 与用户多轮交互 |
| `prd_review` | GATE-1 等 PRD 批准（仅 feature） | 等用户 |
| `plan_review` | GATE-2 等方案卡批准 | 等用户 |
| `working` | 实现 + GATE-V 机器验证 | 主线程连续干完 |
| `deliver_confirm` | GATE-3 等交付三合一确认 | 等用户 |
| `done` | PR 已合并、清理完成 | — |

bugfix / chore 跳过 `prd_review`：诊断结论并入方案卡，只走一个 Gate（plan_review）。
v1 的 bugfix/chore 阶段裁剪规则表不再需要——统一方案卡的瘦版天然覆盖。

## 需求锚定协议（为什么这样设计）

漂移的三个根因，每个对应一条强制纪律：

| 根因 | 症状 | 对策 |
|------|------|------|
| 原话没有锚定物 | 每轮转述都是有损拷贝，越问越偏 | 原话逐字冻结进 PRD 第 1 节；第一轮复述核心诉求并确认 |
| 加法式提问 | "要不要也支持 X？"把没提过的东西种进需求 | 只做填空式提问；模型补充只能以 `[推断]` 条目存在，显式确认前不得进入需求 |
| 合成太晚、审查面太大 | 漂移烤熟了才被看见 | 每轮展示 running summary；GATE-1 只看"超出原话的条目清单" |

## 产物

| 产物 | 路径（task 工作区） | 归档（`.devflow/tasks/<task-id>/`） |
|------|--------------------|-----------------------------------|
| PRD | `.devflow/prd.md` | `prd-<task-slug>.md` |
| 方案卡 | `.devflow/card.md` | `card.md` |
| 验证报告 | `.devflow/verification-report.md` | `verification-report.md` |
| 交付状态 | `.devflow/delivery.yaml` | `delivery.yaml` |

追溯链：**原话 → 需求 R# → 验收标准 A# → verifier 证据**。方案卡的每条验收标准
必须映射 R#；verifier 的每条结论必须带证据——用证据链替代流程完整性。

## GATE-V：唯一 subagent

`devflow-verifier`（从 v1 tester 改造）以干净上下文独立验证：

- 只测不改；`Write` 仅限验证报告
- 逐条执行验收标准：`cmd`（exit 0 即 PASS）/ `ai`（必须附文件行号或 grep 匹配）/ `manual`（留给 GATE-3）
- 无证据不得 PASS；环境缺失标 BLOCKED，不在范围标 SKIP
- 回归命令从项目配置识别，识别不出标 BLOCKED，不猜
- FAIL → 主线程自己修复重验（连续 3 轮失败停下报告用户）；无路由仪式

## 人工介入点（4 个）

1. **需求澄清（Q&A）**——锚定协议下的多轮交互
2. **PRD 评审（GATE-1）**——漂移聚焦审查，批准前待确认项清零
3. **方案卡评审（GATE-2）**——批准方案与验收标准（冻结）
4. **交付确认（GATE-3）**——三合一（commit + push + PR），附验证报告与 manual 项；PR 创建后暂停不自动合并

Gate 之外的阶段由主线程连续推进到下一个 Gate，不需要用户打 `/devflow next`。
`/devflow next` 只用于会话中断恢复和 PR 合并后的 done 清理。
