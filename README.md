# AEW v0 — Project Situational Awareness

> **Scope Contract（冻结）**：AEW v0 是一个面向长期工程项目的状态解析与上下文投影视图：
> 它从项目现有真源中恢复项目身份、任务、近期事件、当前有效决策、相关资产与任务依赖，
> 并生成可供人或 Agent 直接消费的 Project Snapshot。
> **v0 不负责执行任务、启动 Agent、调度模型或实施工程控制。**

> **状态：v0 FREEZE**（2026-09-02，人工确认后冻结）。下一项需求来自真实 dogfood 的骂点，
> 不来自预设路线图。

## 它回答一个问题

进入一个工程 Project，AEW 立刻告诉你「这个项目现在到底是什么情况」。

```
进入 Project → AEW 建立 Project Snapshot → 回答六个问题
1. 这是什么项目？
2. 现在有哪些任务？
3. 最近发生了什么？
4. 哪些决策当前有效？
5. 哪些文件/资产和当前工作相关？
6. 哪些任务现在可以并行？
```

## 运行

```bash
cd C:/Users/fuker/Desktop/workspace
python -m aew.cli C:/Users/fuker/Desktop/workspace/aedl
```

真实输出（AEDL）：

```
AEW PROJECT SNAPSHOT
Project
AEDL — Autonomous Engineering Design Loop · 自主嵌入式工程研发闭环

Current Tasks
W4A          OPEN
W4B          CLAIMED
W4C          OPEN
Sandbox-V3   OPEN

Recent Activity
09-02 09:00  Merge origin/master into docs/agent-report-bundle-path (PR #25 ...)

Active Decisions
[ADR-002] 根 AGENTS v1.4 作为 AEDL 当前唯一执行规范
...

Declared Assets (owned paths)
W4A
  src/hardware/edd001-board/evidence/
  docs/
W4B
  notes/open_source_intake/

Parallel-ready (declared dependencies)
W4A
W4C
Sandbox-V3
```

> `Parallel-ready` 派生自**显式 Task status + 已声明 dependency**，仅此而已——它不宣称
> 「工程上绝对可以同时做」，只是「按当前声明的状态和依赖，它们是 ready」。UNKNOWN 不冒充 Verified。

## 验收标准（六项，窄定义）

| 项                | 真源                           | 实现                    | 定义                                          |
| ----------------- | ------------------------------ | ----------------------- | --------------------------------------------- |
| 项目是什么        | `README.md`                    | `_identity()`           | 标题 + tagline + 北极星                       |
| 当前有哪些任务    | `docs/WAVE4_TASKS_20260901.md` | `_tasks()`              | tracking table + `## TASK-*` 结构发现         |
| 最近发生了什么    | `git log`                      | `_events()`             | Git activity                                  |
| 哪些决策当前有效  | `docs/compliance/DECISIONS.md` | `_decisions()`          | 解析 `状态：`，只显示 current                 |
| 哪些文件/资产相关 | 任务卡「领地」行               | `_assets_for_task()`    | **窄定义：Declared assets / owned paths**     |
| 哪些任务可并行    | 依赖 DAG                       | `deps.parallel_ready()` | **窄定义：显式 status + declared dependency** |

## Repo-native first

AEW **不要求**项目把资料搬进 AEW。它站在现有项目上面，读 README / 任务卡 / DECISIONS /
git log，resolve 成统一视图。这与 Run 001 吻合：Agent 找得到东西，真正的问题是状态会漂移——
v0 把分散真源解析成单一快照。

## 目录（极简）

```
aew/
├── model.py        # 六项数据模型 + render
├── deps.py         # parallel-ready（deterministic DAG，非 AI scheduler）
├── loaders/aedl.py # AEDL repo-native 读取器
├── cli.py          # python -m aew.cli <repo>
└── tests/          # 12 用例
```

## v0 最终状态

```
AEW v0
STATUS:    PRODUCT SLICE EXISTS
SCOPE:     Project Situational Awareness
WRITE:     none
EXECUTION: none
AECP:      separate / unchanged
NEXT:      dogfood —— 真用几天，骂点才是下一项需求
```

## 原来的 aew-core 呢？

`aew-core/`（Task/Attempt/Proposal/Capability/CodeGraph/AECP）**降级为 future semantics
experiments**，不当产品主线。v0 只有这里的东西——状态解析 + 投影，仅此而已。
