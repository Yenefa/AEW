# AEW — Project Situational Awareness + Terminal Decision Layer

> AEW 是一个面向长期工程项目的**状态解析 + 决策投影**系统。它分两层：
>
> - **v0 · Project Brain（冻结）**：从项目现有真源恢复身份、任务、事件、决策、资产、依赖，生成 Project Snapshot。**只读，不执行。**
> - **v1 · Terminal Decision Layer（本仓库新增）**：一个长期运行的 Terminal Agent，把 Snapshot 转成**难度评级 + 模型路由 + 任务卡**，分发给任意 Worker Agent。**不直接实施工程变更；仅负责决策与显式授权后的 Worker 分发。**
> - **v2 · AEW Hub（团队协调层，MVP）**：一个跑在服务器上的 SQLite+HTTP 服务，让**两个人**看到同一个团队任务看板、原子领取任务、再各自本地拆卡分发。

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

# 打印某条任务的 AECP Task Envelope（TaskCard → tasks/GH-N.yaml 桥接）
python -m aew.cli envelope <repo-path> 1

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
envelope <n>        生成 AECP Task Envelope（决策层 → 执行层桥接）
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
├── ids.py          # 稳定任务 ID（AEDL-W4A / GH-PR-42 / GH-ISSUE-37 / GH-CI-ref）
├── github.py       # v1 GitHub Loader（PR/Issue/CI/branch/release）
├── state.py        # v1 持久记忆（.aew/*.json）
├── planner.py      # v1 任务规划 + 0-10 难度评级（显式难度优先）
├── router.py       # v1 模型路由 + 成本台账
├── dispatch.py     # v1 任务卡 → Worker Agent 命令
├── envelope.py     # v2 TaskCard → AECP Task Envelope bridge
├── agent.py        # v1 长期 Terminal Agent REPL
├── hub_client.py   # v2 Local AEW ↔ Hub 客户端（读 AEW_HUB_* 环境变量）
├── hub/            # v2 Hub 服务端（SQLite + HTTP，纯 stdlib）
│   ├── models.py   #   TeamTask + 稳定状态 READY/CLAIMED/BLOCKED/DONE
│   ├── store.py    #   三表 SQLite + 原子 claim
│   ├── sync.py     #   稳定 ID 派生 + refresh（不覆盖 CLAIMED/DONE）
│   ├── coordinator.py  # store + sync 胶水
│   └── api.py      #   8 endpoint http.server + Bearer 认证
├── cli.py          # python -m aew.cli [agent|plan|dispatch|envelope|hub] <repo>
├── loaders/aedl.py # AEDL repo-native 读取器
├── examples/
│   └── sample_project/   # 离线可跑的最小演示项目
└── tests/          # 111 用例（v0 DAG + v1 全组件 + v2 Hub/envelope/e2e）
```

---

## v2 — AEW Hub（团队协调层，MVP）

两个人各自在不同电脑启动 Local AEW，看到同一个团队任务看板；一人领取任务，另一人立刻看到；领取后再各自本地拆卡、选模型、发给 Worker。

### 最小架构与三个真源

```
GitHub / AEDL（仓库事实真源）
        │
        ▼
AEW Hub Server（SQLite + HTTP）—— 只存团队协调状态（谁领了哪个任务）
        │ HTTP
   ┌────┴────┐
   ▼         ▼
 你的 AEW   朋友 AEW      （本地 planner / router / dispatch 不变）
```

| 数据                                    | 真源               |
| --------------------------------------- | ------------------ |
| commit / PR / CI / Issue / branch       | GitHub             |
| 团队任务 owner / claim / shared state    | AEW Hub SQLite     |
| 个人 focus / 本地子任务 / worker 状态     | 各自 Local `.aew/` |

### 运行

```bash
# 服务器（一台机器，走 Tailscale 私网，8765 不裸暴露公网）
export AEW_HUB_TOKEN=<random-long-token>
python -m aew.cli hub <repo-path> --host 0.0.0.0 --port 8765

# 两台电脑各自的 Local AEW
export AEW_HUB_URL=http://100.x.x.x:8765
export AEW_HUB_TOKEN=<同一个 token>
export AEW_USER=Maple      # 另一台是 Ryan
python -m aew.cli agent <repo-path> --github
```

REPL 新增命令：

```
team                团队任务看板（READY / CLAIMED / BLOCKED / DONE）
claim <id>          领取任务（原子，两人抢只有一人成功）
mine                我领取的任务
dispatch-team <n>   把我领取的任务转成 TaskCard 分发（dry-run）
run-team <n> [tgt]  真正分发
release <id>        释放任务
done <id>           标记完成
sync                让 Hub 从仓库刷新
```

### 关键约束

- **稳定任务 ID**：`AEDL-W4A` / `GH-PR-42` / `GH-ISSUE-37` / `GH-CI-<ref>`，刷新 100 次不重复、不复制。
- **原子 claim**：`UPDATE ... WHERE status='READY'` + `rowcount`，两人同时抢同一任务必有一人失败。
- **refresh 不覆盖**：Hub 刷新重新发现任务时，绝不覆盖已 CLAIMED / DONE 的 owner 与状态。

Hub API 只 8 个 endpoint（`/health` `/snapshot` `/tasks` `/tasks/mine` `/refresh` `/tasks/{id}/claim|release|done`），SQLite 三张表，共享 Bearer token 认证。

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