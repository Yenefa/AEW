# AEW — Project Situational Awareness + Terminal Decision Layer

> AEW 是一个面向长期工程项目的**状态解析 + 决策投影**系统。它分两层：
>
> - **v0 · Project Brain（冻结）**：从项目现有真源恢复身份、任务、事件、决策、资产、依赖，生成 Project Snapshot。**只读，不执行。**
> - **v1 · Terminal Decision Layer（本仓库新增）**：一个长期运行的 Terminal Agent，把 Snapshot 转成**难度评级 + 模型路由 + 任务卡**，分发给任意 Worker Agent。**不直接实施工程变更；仅负责决策与显式授权后的 Worker 分发。**

> 一句话：**让 AI 工程团队拥有一个不会失忆的项目负责人。**

---

## 它回答什么问题

进入一个工程 Project，AEW 立刻告诉你「现在什么情况，下一步该做什么」。

```
进入 Project → Project Snapshot → 回答六个问题（v0）
                                  ↓
                     Task Planner → 拆任务、评难度（v1）
                                  ↓
                     Model Router → 选模型（v1）
                                  ↓
                     Task Card    → 任何 Agent 可接（v1）
```

---

## v0 — Project Brain（冻结）

### 六个字段

| 项                | 真源                           | 实现                    |
| ----------------- | ------------------------------ | ----------------------- |
| 项目是什么        | `README.md`                    | `_identity()`           |
| 当前有哪些任务    | `docs/WAVE4_TASKS_*.md`        | `_tasks()`              |
| 最近发生了什么    | `git log`                      | `_events()`             |
| 哪些决策当前有效  | `docs/compliance/DECISIONS.md` | `_decisions()`          |
| 哪些文件/资产相关 | 任务卡「领地」行               | `_assets_for_task()`    |
| 哪些任务可并行    | 依赖 DAG                       | `deps.parallel_ready()` |

> `Parallel-ready` 派生自**显式 status + 已声明 dependency**，仅此而已——UNKNOWN 不冒充 Verified。

### Repo-native first

AEW **不要求**项目把资料搬进 AEW。它站在现有项目上面读 README / 任务卡 / DECISIONS / git log，resolve 成统一视图。

---

## v1 — Terminal Decision Layer（新增）

v1 在 v0 之上加了三件事：**项目全局感知**、**任务规划与难度评级**、**模型路由与分发**，并用**持久记忆**解决 session 失忆。

### 核心组件

```
             Terminal Agent  (agent.py  · 项目负责人，不执行)
                     |
        +------------+------------+
        |                         |
   Project Brain              Decision Layer
   (v0 Snapshot)              (planner → router → dispatch)
        |                         |
   GitHub Loader             Persistent Memory
   (github.py)               (state.py · .aew/*.json)
```

| 组件            | 文件          | 职责                                                     |
| --------------- | ------------- | -------------------------------------------------------- |
| Project Brain   | `model.py` / `loaders/` / `deps.py` | 六字段 Snapshot（v0）+ PR/Issue/CI/Release 字段（v1） |
| GitHub Loader   | `github.py`   | 读 PR / Issue / CI / branch / release，离线优雅降级       |
| Persistent Mem  | `state.py`    | `.aew/` 下 project_state / active_tasks / focus 三份 JSON |
| Task Planner    | `planner.py`  | Snapshot → 任务列表 + 0-10 难度评级                        |
| Model Router    | `router.py`   | 模型池 + 规则路由 + 成本台账                              |
| Agent Dispatch  | `dispatch.py` | 任务卡 → OpenCode / Claude Code / Codex / API 命令         |
| Terminal Agent  | `agent.py`    | 长期运行的交互式项目负责人 REPL                            |

### 难度评级（0-10，确定性）

| 因素            | 增加 |
| --------------- | ---: |
| 修改文件 > 5    | +1   |
| 跨模块          | +2   |
| 架构变化        | +3   |
| 硬件影响        | +2   |
| 需要验证        | +1   |
| 涉及安全/合规   | +2   |

| 分数      | 档位           | 模型       |
| --------- | -------------- | ---------- |
| 0-3       | simple         | Flash      |
| 4-7       | standard       | 中端       |
| 8-10      | architectural  | 旗舰       |

### 模型路由（规则化，无 LLM 调用）

- 需要图像/硬件分析 → `vision`（gemini-flash）
- 简单任务 → `cheap`（z-ai/glm-5.3-flash）
- 标准任务 → `mid`
- 架构任务 → `strong`（claude / gpt）

模型池可在 `<repo>/models.yaml` 覆盖（YAML 或 JSON）。

### 任务卡（分发工件）

任何 Agent 都能直接接住，无需重新推导上下文：

```yaml
task_id: AEDL-DEMO-20260903-001
title: Implement W4A
objective: evidence validator
project: AEDL-Demo
current_stage: Build
files: [src/hardware/edd001-board/evidence/, docs/]
difficulty: 5
recommended_model: gemini-flash
acceptance: [tests pass, task marked DONE]
```

---

## 运行

```bash
cd <parent-of-aew>

# v0：打印六字段 Snapshot
python -m aew.cli <repo-path>

# 打印任务计划（难度 + 模型）
python -m aew.cli plan <repo-path>

# 打印某条任务的分发命令（dry-run，不真正执行）
python -m aew.cli dispatch <repo-path> 1

# 启动长期 Terminal Agent REPL
python -m aew.cli agent <repo-path>

# 任意命令追加 --github 可额外投影 PR / Issue / CI / Release
python -m aew.cli agent <repo-path> --github
```

### Terminal Agent 命令

```
status | s          当前项目仪表盘
tasks  | plan       列出计划任务（难度 + 推荐模型）
show <n>            查看完整任务卡
dispatch <n> [tgt]  打印分发命令（dry-run）
run <n> [tgt]       真正分发到 Worker Agent
focus <text>        设置当前关注点（持久化）
recover             上次会话留下了什么
agents              本机可用的 Worker Agent
models              模型池
quit                保存记忆后退出
```

示例（`examples/sample_project`）：

```
AEW Agent online.
Project: AEDL-Demo — Autonomous Engineering Design Loop
Status: 0% complete · 4 open · 0 blocked
Memory: focus: Evidence Validation · last session: 2026-09-03
3 task(s) available.

Recommended:
1. [Medium] Implement W4A  (difficulty 5/10 standard → gemini-flash)
2. [Medium] Implement W4C  (difficulty 0/10 simple → z-ai/glm-5.3-flash)
3. [Medium] Implement Sandbox-V3  (difficulty 3/10 simple → gemini-flash)
>
```

> `[Medium]` 是**优先级**（High/Medium/Low）；`standard` / `simple` 才是**难度档位**（0-3 simple / 4-7 standard / 8-10 architectural）。注意 `Sandbox-V3` 难度 3（simple 档）却路由到 `gemini-flash`——因为它的领地含硬件/原理图，触发了 vision 优先规则（见下「模型路由」）。

### 持久记忆（高信号，非真源）

`.aew/` 只保存**无法从仓库实时重算的高信号上下文**——决策层自己的标注：

| 文件                  | 内容                                             |
| --------------------- | ------------------------------------------------ |
| `focus.json`          | 当前关注点 + 未完成分发 + 上次会话时间             |
| `active_tasks.json`   | 已分发给 Worker 的在途任务                        |
| `project_state.json`  | Agent 标注：当前 phase                            |

**PR / Issue / CI / Release 状态绝不落盘**——它们由 GitHub Loader 每次启动实时读取（`--github`）；任务数、阻塞数、完成度也从 Snapshot 每次重算。`.aew/` 不是这些状态的第二份真源，避免 fork 出一份会过期的缓存。

会话结束写入 `<repo>/.aew/`，下次 `agent` 启动直接恢复——**不保存聊天**。`.aew/` 默认 gitignore；团队可自行决定是否提交以共享项目连续性。

---

## 目录

```
aew/
├── model.py        # v0 六字段 + v1 PR/Issue/CI/TaskCard/ResultCard 数据模型
├── deps.py         # parallel-ready（deterministic DAG）
├── github.py       # v1 GitHub Loader（PR/Issue/CI/branch/release）
├── state.py        # v1 持久记忆（.aew/*.json）
├── planner.py      # v1 任务规划 + 0-10 难度评级
├── router.py       # v1 模型路由 + 成本台账
├── dispatch.py     # v1 任务卡 → Worker Agent 命令
├── agent.py        # v1 长期 Terminal Agent REPL
├── cli.py          # python -m aew.cli [agent|plan|dispatch] <repo>
├── loaders/aedl.py # AEDL repo-native 读取器
├── examples/
│   └── sample_project/   # 离线可跑的最小演示项目
└── tests/          # 58 用例（含 v0 DAG + v1 全部新组件）
```

---

## 与 v0 的关系

不是替代，是分层：

```
AEW (Project Brain)        = 事实层（读状态）
Terminal Agent             = 决策层（拆任务、评难度、选模型、发任务卡）
Worker Agent (OpenCode/…)  = 执行层（接任务卡干活）
```

v0 的 Scope Contract（**只读、不执行**）不变；v1 全部新增能力也**不直接改代码**——只生成任务卡与命令，仅在显式 `run` 时把命令交给 Worker Agent 执行。

## MVP 实现路线（进度）

- [x] Phase 1 · Project Awareness —— GitHub Loader + Snapshot 增强
- [x] Phase 2 · Task System —— Task Planner + Task Card + Difficulty Rating
- [x] Phase 3 · Model Router —— Model Pool + Rule Router + Cost Tracking
- [x] Phase 4 · Agent Dispatch —— OpenCode / Claude Code / Codex / API Agent

---

## 测试

```bash
python -m unittest discover -s aew/tests -t .
# OK (skipped=10) —— 10 个为原作者针对私有 AEDL 仓库的集成测试，缺仓时自动跳过
```
