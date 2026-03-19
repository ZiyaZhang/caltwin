# Spec: C — Shadow Mode Demo + Trajectory Visualization

> **Status**: v5（v2 7 项 + v3 8 项 + v4 9 项 + v5 6 项修正）
> **项目**: twin-runtime
> **前置依赖**: A（A/B Baseline Runner）+ B（Bootstrap Protocol）+ D（Implicit Reflection + OpenClaw Skill）
> **预估工期**: 5-6 天

### Review 修正记录

**v2 修正（7 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 1 | 高 | ShadowPredictor._detect_decision 和 Claude Code 重复检测 | 删掉 _detect_decision，接收 question+options 作为输入 |
| 2 | 中 | shadow --status 持久化缺失 | 加 shadow_log.jsonl 文件，TraceStore 中标记 shadow traces |
| 3 | 中 | shadow auto-reflect 触发机制不明 | SKILL.md 明确 Claude Code 在用户选择后主动调 reflect |
| 4 | 低 | ExperienceLogEntry vs ExperienceChangeEntry 命名不一致 | 统一为 ExperienceChangeEntry |
| 5 | 中 | ExperienceChangeLog 存储位置未指定 | 独立 JSONL 文件，不污染 ExperienceLibrary 模型 |
| 6 | 低 | C4 ComparisonExecutor 接口适配未检查 | spec 中给出与代码对齐的实际调用签名 |
| 7 | 中 | demo 数据生成依赖 flywheel 脚本但不保存快照 | prepare_demo_data.py 自己跑完整流程 |

**v3 修正（8 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 12 | 高 | ShadowPredictor 调用路径混乱：数据流图写 CLI 调用，但代码中 ShadowPredictor 用 Python API | 明确两种模式：CLI 模式（Claude Code 直接调 CLI）+ MCP 模式（shadow_predict tool） |
| 13 | 中 | shadow_log.json 每次全量读写，O(n) 性能 | 改为 JSONL append-only 格式 |
| 14 | 中 | ExperienceChangeLog 放在 ExperienceLibrary 模型中，导致 library JSON 无限增长 | 独立存储为 experience_change_log.jsonl |
| 15 | 中 | C4 ComparisonExecutor 调用签名与代码不匹配 | 对齐实际签名：`ComparisonExecutor(runners=[实例列表], twin=twin)` |
| 16 | 中 | was_correct 回填触发点未指定 | 在 cmd_reflect 中反查 shadow_log，自动回填 |
| 17 | 低 | _append_log 手写 atomic write，未复用项目已有 _utils.atomic_write | 统一使用 atomic_write |
| 18 | 低 | rolling CF 窗口 window_size = min(10, total/2) 边界条件 total=1 时 = 0 | 改为 max(1, min(10, total // 2)) |
| 19 | 低 | Demo 数据 prepare_demo_data.py 需要 API key，CI 无法自动化 | 明确为一次性生成后 git commit 的静态资源 |

**v4 修正（9 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 28 | 高 | ShadowPredictor.predict() 缺少 evidence_store 参数，S2 deliberation 无法检索证据 | __init__ 和 predict() 传透 evidence_store |
| 29 | 中 | was_correct 回填逻辑用 `in` 操作不精确（"Redis" in "Use Redis..."误判） | 复用 fidelity_evaluator.choice_similarity |
| 30 | 中 | TraceStore Port list_traces(user_id) 第一参数无默认值，但所有调用方都不传 | Port 签名改为 user_id="" 默认值（已在代码中修复） |
| 31 | 中 | ExperienceChangeEntry 在 Phase D 中不存在，C Step 0 需要新建但 spec 未明确 | 明确标注为 C 新增 domain model |
| 32 | 中 | shadow_log_path 硬编码 Path.home()，与 CLI _STORE_DIR 配置可能不一致 | 统一从 config 读取 store_dir |
| 33 | 低 | _append_log 用普通 open("a") 但 spec #17 说要用 atomic_write，描述不一致 | 统一说法：追加写不需要 atomic，只有 backfill 全量重写需要 |
| 34 | 低 | SKILL.md 路径 .claude/skills/ 与 skills/openclaw/ 关系未说明 | 说明：.claude/skills 是 Claude Code 本地 skill，skills/openclaw/ 是 OpenClaw 分发 skill |
| 35 | 低 | demo/ 目录与 --demo CLI flag 的关系可能造成混淆 | demo/ 目录仅供 prepare_demo_data.py 和 investor_demo.py，与 --demo flag 使用的 fixtures 独立 |
| 36 | 低 | OutcomeStore Port list_outcomes 缺少 limit 参数，JSON/SQLite 实现不兼容 | Port 签名加 limit=500（已在代码中修复） |

**v5 修正（6 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 44 | 中 | ShadowPredictor.predict() 调用 orchestrator.run() 但不持久化 trace，reflect --trace-id 无法找回 | predict() 接收 trace_store 并在 pipeline run 后显式持久化 trace |
| 45 | 中 | backfill_was_correct 全量读写无上限，长期运行后 shadow_log 可达数千行 | 添加 90 天归档策略：backfill 时自动归档旧记录到 shadow_log.archive.jsonl |
| 46 | 中 | cmd_reflect 回填需构造完整 ShadowPredictor 实例（需 6 个参数），但只用 log_path | 抽取 backfill 为独立函数 backfill_shadow_log(log_path, trace_id, was_correct) |
| 47 | 低 | compute_trajectory 参数风格不一致：outcomes/traces 是对象，change_log 是 Path | 统一为全部传入已加载对象，调用方负责解析 |
| 48 | 低 | Shadow Mode demo segment 依赖实时 Claude Code 会话，LLM 延迟不可控 | 明确 Shadow Mode 段为预录屏幕录像 + voiceover |
| 49 | 低 | suppressed prediction（confidence < 0.4）的 was_correct 回填行为未说明 | 明确：suppressed prediction 永远不回填（prediction 为空，无法比对） |

---

## C 的定位

C 是**面向投资人的 demo 层**。ABD 完成了核心引擎（pipeline + bootstrap + implicit flywheel），C 把这些能力包装成一个可演示、可量化的故事。C 不新增核心算法——它消费 ABD 的数据，生成可视化和演示脚本。

---

## C1: Shadow Mode Claude Code Skill

### 问题

目前 twin-runtime 只在用户主动 `twin-runtime run` 时介入。Shadow Mode 让 twin 在用户正常工作时**被动预测**——用户做决策时 twin 实时显示"我觉得你会选 X"，不干预，只展示。这是 demo 中最有冲击力的环节：投资人看到 twin 在真实工作流中实时预测。

### 设计

```
.claude/skills/twin-shadow/
├── SKILL.md           # Claude Code skill
└── shadow_mode.py     # 辅助脚本
```

**SKILL.md 核心指令**（修正 #1 #3）：

```yaml
---
name: twin-shadow
description: >
  Shadow mode for twin-runtime. Silently predicts user decisions in real-time
  during work sessions. Shows predictions as non-intrusive annotations.
---

# twin-runtime Shadow Mode

## When to activate
- User faces a decision during normal coding/work session
- Decision has 2+ clear options
- Decision falls in twin's modeled domains

## Shadow behavior
1. Extract question and 2-4 options from conversation context
2. Run: `twin-runtime run "<question>" -o "<opt1>" "<opt2>" --json`
3. Parse JSON output. If confidence >= 0.4, display prediction as a subtle note:
   "🔮 Twin prediction: [option] (confidence: X%)"
   If confidence < 0.4, stay silent (don't clutter).
4. Do NOT influence the user's choice — prediction is informational only.
5. **After user makes their choice** (修正 #3): immediately record it:
   `twin-runtime reflect --trace-id <id> --choice "<actual>" --source user_correction`
   This closes the feedback loop within the same Claude Code session.

## Consistency conflict display
When the JSON output includes a consistency_note:
- Show: "⚠️ This differs from your usual pattern in [scenario_type]"
- Cite the conflicting ExperienceEntry

## Boundaries
- Same as main twin: REFUSE/DEGRADE rules apply
- Shadow mode NEVER overrides user action
- If twin is not initialized, skip silently
```

### 新增 CLI

```
twin-runtime shadow --enable     # 写入 config: shadow_mode=true
twin-runtime shadow --disable
twin-runtime shadow --status     # 显示 shadow 统计（从 shadow_log.jsonl 读取）
```

`shadow --status` 输出：

```
Shadow Mode: ENABLED
Session predictions: 12
  Correct: 9 (75%)
  Pending: 2
  Wrong: 1
Silence rate: 3/15 (20% — low confidence suppressed)
```

**shadow_log.jsonl 存储位置**：`~/.twin-runtime/store/<user_id>/shadow_log.jsonl`。JSONL 格式，每行一条记录（修正 #13：append-only，无需全量读写）。reflect 完成后通过 trace_id 回填 was_correct。

### 调用路径（修正 #12：明确两种模式）

Shadow Mode 有两种调用路径，针对不同集成场景：

**模式 A: CLI 模式（Claude Code SKILL.md 使用）**

Claude Code 直接调现有 CLI `twin-runtime run --json`。Shadow-specific 逻辑（log 追加、低置信度抑制）放在 `cli/_shadow.py` 中：

```
twin-runtime shadow-run "<question>" -o "<opt1>" "<opt2>"
```

等价于 `twin-runtime run --json` + 自动追加 shadow_log.jsonl + 自动抑制低置信度输出。这是一个**薄包装**，不引入新的 Python 类。

**模式 B: MCP 模式（IDE 插件使用）**

在 MCP server 中新增 `twin_shadow_predict` tool，调用 `ShadowPredictor.predict()`。适用于 Claude Desktop 等非 CLI 环境。

```python
# server/mcp_server.py — 新增 tool
{
    "name": "twin_shadow_predict",
    "description": "Shadow mode: predict user's decision without influencing it",
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["question", "options"]
    }
}
```

### 实现（修正 #1 #12 #13 #28 #32 #33 #44 #45 #46 #49）

```python
# src/twin_runtime/application/shadow/shadow_predictor.py

from twin_runtime.infrastructure.backends.json_file._utils import atomic_write

class ShadowPredictor:
    """
    被动预测器。接收 Claude Code 已提取好的 question + options，
    运行 pipeline 并返回预测。不做二次决策检测（Claude Code LLM 已做）。

    调用方：
    - CLI 模式: cli/_shadow.py 的 cmd_shadow_run 调用
    - MCP 模式: server/mcp_server.py 的 _handle_shadow_predict 调用
    """

    def __init__(self, twin_store, experience_store, evidence_store,
                 trace_store, llm, user_id: str, store_dir: Path):
        # 修正 #28: 接收 evidence_store，S2 deliberation 需要检索证据
        # 修正 #32: 接收 store_dir 而非硬编码 Path.home()
        # 修正 #44: 接收 trace_store，pipeline run 后持久化 trace
        self._twin_store = twin_store
        self._experience_store = experience_store
        self._evidence_store = evidence_store
        self._trace_store = trace_store
        self._llm = llm
        self._user_id = user_id
        self._min_confidence = 0.4
        self._log_path = Path(store_dir) / user_id / "shadow_log.jsonl"

    def predict(self, question: str, options: List[str]) -> ShadowPrediction:
        """
        输入：Claude Code 提取好的 question + options。
        输出：ShadowPrediction（可能 suppressed=True）。
        """
        from twin_runtime.application.orchestrator.runtime_orchestrator import run
        twin = self._twin_store.load_state(self._user_id)
        exp_lib = self._experience_store.load()

        trace = run(
            query=question,
            option_set=options,
            twin=twin,
            llm=self._llm,
            evidence_store=self._evidence_store,  # 修正 #28
            experience_library=exp_lib,
        )

        # 修正 #44: 持久化 trace 以便后续 reflect --trace-id 能找到
        self._trace_store.save_trace(trace)

        confidence = 1 - trace.uncertainty
        suppressed = confidence < self._min_confidence

        prediction = ShadowPrediction(
            trace_id=trace.trace_id,
            question=question,
            prediction=trace.final_decision if not suppressed else "",
            confidence=confidence,
            consistency_conflict=trace.consistency_note,
            suppressed=suppressed,
            reason="Low confidence" if suppressed else "",
        )

        self._append_log(prediction)
        return prediction

    def _append_log(self, prediction: ShadowPrediction):
        """Append-only JSONL 持久化（修正 #13）。

        追加写不需要 atomic_write（修正 #33）。
        """
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        line = prediction.model_dump_json() + "\n"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def load_log(self) -> List[ShadowPrediction]:
        """读取全部 shadow log（用于 --status 命令）。"""
        if not self._log_path.exists():
            return []
        predictions = []
        for line in self._log_path.read_text().splitlines():
            if line.strip():
                predictions.append(ShadowPrediction.model_validate_json(line))
        return predictions


class ShadowPrediction(BaseModel):
    trace_id: str
    question: str = ""
    prediction: str = ""
    confidence: float = 0.0
    consistency_conflict: Optional[str] = None
    suppressed: bool = False
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    was_correct: Optional[bool] = None  # 回填 by reflect


# --- 独立函数：shadow log 操作（修正 #46：不依赖 ShadowPredictor 实例） ---

def backfill_shadow_log(
    log_path: Path, trace_id: str, was_correct: bool,
    archive_days: int = 90,
):
    """回填 was_correct 并归档旧记录（修正 #45 #46）。

    独立函数，只需要 log_path — cmd_reflect 无需构造完整 ShadowPredictor。
    同时归档 >archive_days 天的记录到 shadow_log.archive.jsonl，
    防止 shadow_log 无限增长（修正 #45）。

    修正 #49: suppressed prediction（prediction 为空）永远不回填。
    """
    if not log_path.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=archive_days)
    archive_path = log_path.with_suffix(".archive.jsonl")

    lines = log_path.read_text().splitlines()
    current = []
    archived = []

    for line in lines:
        if not line.strip():
            continue
        p = ShadowPrediction.model_validate_json(line)
        # 回填（修正 #49：跳过 suppressed predictions）
        if p.trace_id == trace_id and p.prediction:
            p.was_correct = was_correct
        # 归档旧记录
        if p.timestamp < cutoff:
            archived.append(p.model_dump_json())
        else:
            current.append(p.model_dump_json())

    # 写入归档（append）
    if archived:
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write("\n".join(archived) + "\n")

    # 原子重写当前 log
    atomic_write(log_path, "\n".join(current) + "\n")
```

### was_correct 回填机制（修正 #16 #29 #46 #49）

在 `cli/_calibration.py` 的 `cmd_reflect` 中，reflect 成功后自动检查 shadow_log：

```python
# cli/_calibration.py — cmd_reflect 末尾新增
shadow_log_path = _STORE_DIR / user_id / "shadow_log.jsonl"  # 修正 #32: 用 _STORE_DIR
if shadow_log_path.exists() and args.trace_id:
    from twin_runtime.application.shadow.shadow_predictor import (
        backfill_shadow_log, ShadowPrediction,
    )
    from twin_runtime.application.calibration.fidelity_evaluator import choice_similarity

    # 修正 #29: 复用 choice_similarity 替代简陋的 `in` 操作
    # 修正 #46: 用独立函数，无需构造完整 ShadowPredictor
    # 先读取 prediction 用于判断 was_correct
    for line in shadow_log_path.read_text().splitlines():
        if not line.strip():
            continue
        entry = ShadowPrediction.model_validate_json(line)
        if entry.trace_id == args.trace_id and entry.prediction:
            # 修正 #49: suppressed (prediction=="") 跳过
            score, rank = choice_similarity([entry.prediction], args.choice)
            was_correct = rank == 1
            backfill_shadow_log(shadow_log_path, args.trace_id, was_correct)
            break
```

### 数据流（修正 #1 #3 #12）

```
用户正常工作
    ↓
Claude Code LLM 检测到决策场景（基于 SKILL.md "When to activate"）
    ↓
Claude Code 提取 question + options
    ↓
[CLI 模式] twin-runtime shadow-run "<question>" -o "<opt1>" "<opt2>"
[MCP 模式] twin_shadow_predict tool call
    ↓
ShadowPredictor.predict(question, options) → pipeline run
    ↓ (confidence >= 0.4)
显示 "🔮 Twin prediction: ..."  +  append 到 shadow_log.jsonl
    ↓ (用户做出选择后)
Claude Code 主动调用 twin-runtime reflect --trace-id <id> --choice "<actual>"
    ↓
cmd_reflect → 回填 shadow_log.jsonl 中该 trace_id 的 was_correct
```

---

## C2: Fidelity Trajectory Visualization

### 问题

投资人需要**一张图**证明 flywheel 在转。这张图是 demo 的核心视觉证据。

### 两张图

**图 1: CF vs Decision Count（时序轨迹）**

- X 轴：决策序号（1, 2, 3, ...）
- Y 轴：滚动 CF（rolling window = max(1, min(10, total // 2))）（修正 #18：防止 total=1 时 window=0）
- 标注线：human baseline at 0.85（Stanford Digital Twin test-retest）
- 标注区域：bootstrap 阶段（前 N 个决策用灰色背景）
- 数据源：OutcomeStore 中的 outcomes 按时间排序

**图 2: CF vs Experience Library Size（缩放律）**

- X 轴：ExperienceLibrary.size（entries 数量）
- Y 轴：对应时间段的 CF
- 目的：证明 experience 增长 → CF 提升的因果关系
- 标注：bootstrap entries（初始 6-10 条）vs implicit reflection entries

### 实现

```python
# src/twin_runtime/application/visualization/trajectory.py

class TrajectoryData(BaseModel):
    """twin-runtime trajectory 输出的数据结构。"""
    decisions: List[DecisionPoint]
    rolling_cf: List[float]          # 滚动 CF 值
    window_size: int
    experience_sizes: List[int]      # 每个决策时的 library size
    bootstrap_count: int             # bootstrap 阶段的决策数
    human_baseline: float = 0.85

class DecisionPoint(BaseModel):
    index: int
    trace_id: str
    was_correct: bool
    confidence: float
    source: str                      # user_correction / implicit_git / ...
    experience_size_at_time: int
    timestamp: datetime


def compute_trajectory(
    outcomes: List[OutcomeRecord],
    traces: List[RuntimeDecisionTrace],
    change_log: List[ExperienceChangeEntry],  # 修正 #47: 统一为已加载对象
) -> TrajectoryData:
    """
    从 outcomes + traces + experience change log 计算轨迹数据。
    outcomes 和 traces 通过 trace_id join。
    change_log 由调用方从 JSONL 文件加载后传入（修正 #47：保持参数风格一致）。
    """
    ...
```

### CLI

```
twin-runtime trajectory              # 生成 trajectory 数据 JSON
    [--format json|csv|html]         # 默认 json
    [--output path]                  # 默认 stdout

twin-runtime trajectory --html       # 生成带 Chart.js 的 HTML 报告
    [--open]                         # 生成后在浏览器打开
```

### 前置改动（修正 #14 #31：change log 独立存储，C 新增 model）

**ExperienceChangeEntry 是 C 新增的 domain model**（修正 #31：Phase D 中不存在，需要在 C Step 0 创建）。独立存储为 JSONL 文件，不作为 ExperienceLibrary 的字段。原因：
- change log 是审计数据，不是 library 核心模型
- 放在 ExperienceLibrary 里会导致 library JSON 无限增长（entry 50 条但 change log 可能上千条）
- JSONL append-only 更高效，不需要每次全量序列化

```python
# domain/models/experience.py — C Step 0 新增（当前代码中不存在）
class ExperienceChangeEntry(BaseModel):
    timestamp: datetime
    action: str          # "add" / "confirm" / "supersede" / "pattern_add"
    entry_id: str
    size_after: int
```

**存储位置**：`<store_dir>/<user_id>/experience_change_log.jsonl`（跟随 _STORE_DIR 配置）

ExperienceUpdater 的每个 update() 调用后 append 一条 ExperienceChangeEntry 到这个 JSONL 文件。

```python
# 在 ExperienceUpdater.update() 末尾：
change = ExperienceChangeEntry(
    timestamp=datetime.now(timezone.utc),
    action=result.action,  # "add" / "confirm" / "supersede"
    entry_id=new_entry.id,
    size_after=library.size,
)
# append to JSONL
with open(change_log_path, "a") as f:
    f.write(change.model_dump_json() + "\n")
```

---

## C3: Investor Demo Script

### 5 分钟结构

| 时间 | 环节 | 展示内容 | 数据源 |
|------|------|---------|--------|
| 0:00-0:30 | Problem | "AI agents can do tasks, but can they think like you?" | 叙事 |
| 0:30-1:30 | Bootstrap | 实时运行 `twin-runtime bootstrap`（快进版，预录 answers） | B |
| 1:30-2:30 | Shadow Mode | **预录屏幕录像**：Claude Code 中正常编码，twin 实时预测决策（修正 #48） | C1 |
| 2:30-3:30 | A/B Comparison | 展示 4 个 runner 的 CF 对比柱状图 | A |
| 3:30-4:30 | Trajectory | 展示 CF 曲线从 0.5 → 0.75+ 的增长 | C2 |
| 4:30-5:00 | Ecosystem | "Judgment harness. Mem0 solves recall, we solve judgment." | 叙事 |

### 实现

```python
# scripts/investor_demo.py

class DemoRunner:
    """
    预录的 demo 脚本。使用固定 seed 的 TwinState + 预定义场景，
    确保 demo 可重复、不依赖网络。
    """

    def __init__(self, demo_dir: str = "demo/"):
        self.demo_dir = Path(demo_dir)
        self.bootstrap_answers = self._load("bootstrap_answers.json")
        self.shadow_scenarios = self._load("shadow_scenarios.json")
        self.comparison_data = self._load("comparison_results.json")

    def run_bootstrap_segment(self):
        """快进版 bootstrap：直接注入预录 answers。"""
        ...

    def run_shadow_segment(self):
        """展示 3 个 shadow prediction。
        修正 #48: 此段为预录屏幕录像 + voiceover。
        实时 Claude Code 会话有 LLM 延迟风险，不适合 5 分钟限时 demo。
        DemoRunner 仅播放预录视频，不调用 LLM。
        """
        ...

    def run_comparison_segment(self):
        """展示 A/B Runner 结果（预计算）。"""
        ...

    def run_trajectory_segment(self):
        """展示 trajectory chart（预计算 + 实时更新）。"""
        ...
```

### Demo 数据准备（修正 #7 #19）

```
demo/
├── bootstrap_answers.json        # 预录的 20 个 bootstrap 回答
├── shadow_scenarios.json         # 5 个 shadow mode 场景
├── comparison_results.json       # A/B Runner 预计算结果
├── trajectory_data.json          # 50+ 决策的轨迹数据
├── sample_twin_state.json        # demo 用的 TwinState
└── sample_experience_library.json # demo 用的 ExperienceLibrary
```

数据通过 `scripts/prepare_demo_data.py` 生成：自己跑完整 bootstrap → N 轮 run+reflect 循环，每一步保存 TwinState / ExperienceLibrary / outcome 快照。不依赖 verify_flywheel.py（该脚本只输出最终 CF 数字，不保存中间状态）。

**重要（修正 #19）**：`prepare_demo_data.py` 需要真实 ANTHROPIC_API_KEY 调用 LLM。生成的 demo 数据是**一次性生成后 git commit 的静态资源**，不在 CI 中重新生成。CI 只验证 demo 数据文件的存在和 schema 正确性。

---

## C4: Mini A/B 升级

### 问题

B 的 `_run_bootstrap_comparison` 是手写 mini comparison，不涉及 baseline（vanilla/persona/rag_persona）。Demo 需要展示 "+20pp over baselines" 的数据。

### 方案（修正 #15：对齐实际 ComparisonExecutor 签名）

复用 A 的 `ComparisonExecutor`，替换手写 comparison。

**实际签名**（从代码验证）：

```python
# ComparisonExecutor.__init__(runners: List[BaseRunner], twin: TwinState)
# ComparisonExecutor.load_scenarios(path: Path) -> ScenarioSet
# ComparisonExecutor.run_all(scenario_set: ScenarioSet, ...) -> ComparisonReport
```

注意：`runners` 参数接收 **BaseRunner 实例列表**（不是字符串列表）。

```python
# 在 cmd_bootstrap 的末尾：
if not args.no_comparison:
    from twin_runtime.application.comparison.executor import ComparisonExecutor
    from twin_runtime.application.comparison.runners.vanilla import VanillaRunner
    from twin_runtime.application.comparison.runners.persona import PersonaRunner
    from twin_runtime.application.comparison.runners.twin_runner import TwinRunner

    runners = [
        VanillaRunner(llm=llm),
        PersonaRunner(llm=llm),
        TwinRunner(llm=llm, experience_library=result.experience_library),
    ]
    executor = ComparisonExecutor(runners=runners, twin=result.twin)
    scenario_set = executor.load_scenarios(Path("data/comparison_scenarios.json"))
    report = executor.run_all(scenario_set)

    # 输出摘要
    for rid, agg in report.aggregates.items():
        print(f"  {rid}: CF={agg.cf_score:.2f}")
```

---

## C 集成点

| 现有模块 | 集成方式 |
|----------|---------|
| A: ComparisonExecutor | C4 复用，构造 BaseRunner 实例列表 |
| B: ExperienceLibrary | C2 消费 change log 数据（独立 JSONL 文件） |
| B: Bootstrap | C3 demo 使用预录 answers 快进 |
| D: OutcomeStore | C2 trajectory 的数据源 |
| D: HeartbeatReflector | C1 shadow mode 的 auto-reflect 用同一 API |
| D: ExperienceUpdater | C2 change log 在 updater 中 append |
| D: cmd_reflect | C1 shadow log was_correct 回填触发点（复用 choice_similarity） |

### Skill 路径说明（修正 #34）

项目有两种 skill 分发路径：
- **`.claude/skills/twin-shadow/`**：Claude Code 本地 skill，用户通过 `twin-runtime shadow --enable` 安装到当前工作区的 `.claude/skills/` 目录。仅影响当前工作区。
- **`skills/openclaw/twin-runtime/`**：OpenClaw 分发 skill（已有），通过 OpenClaw 市场安装，跨工作区生效。

Shadow Mode skill 走 `.claude/skills/` 路径，因为它需要 Claude Code 的 conversation context 来检测决策场景，不适合 OpenClaw 的无状态分发模式。

### demo/ 目录说明（修正 #35）

`demo/` 目录仅供 `scripts/prepare_demo_data.py` 生成的静态资源和 `scripts/investor_demo.py` 使用。与 CLI 的 `--demo` flag 独立——`--demo` 使用 `tests/fixtures/` 和 `src/twin_runtime/resources/fixtures/` 中的数据。两者不冲突。

---

## C 测试策略

### Offline

```python
# test_shadow/test_shadow_predictor.py
def test_predict_returns_prediction():      # mock pipeline → ShadowPrediction
def test_low_confidence_suppression():      # uncertainty > 0.6 → suppressed=True
def test_shadow_log_appended():             # predict() → shadow_log.jsonl 新增一行
def test_shadow_log_jsonl_format():         # 每行是独立 JSON（非 JSON array）
def test_shadow_status_reads_log():         # shadow --status 从 log 统计
def test_backfill_was_correct():            # backfill → 对应 trace_id 更新
def test_backfill_missing_trace_id():       # 不存在的 trace_id → no-op

# test_visualization/test_trajectory.py
def test_compute_trajectory():              # 10 outcomes → rolling CF
def test_experience_scaling():              # experience size 增长 → CF 提升
def test_bootstrap_phase_marking():         # 前 N 个决策标记为 bootstrap
def test_empty_outcomes():                  # 无数据 → 空 trajectory
def test_rolling_window_boundary():         # total=1 → window_size=1（不是 0）

# test_demo/test_demo_runner.py
def test_demo_data_integrity():             # demo 数据文件完整性 + schema 正确
def test_bootstrap_segment():               # 预录 answers → 完整 bootstrap
```

### Online

```python
@pytest.mark.requires_llm
def test_shadow_end_to_end():               # 真实 LLM 预测
def test_trajectory_html_generation():      # 生成 HTML → 文件有效
```

---

## C 验收 Checklist

- [ ] Shadow Mode skill 文件创建（.claude/skills/twin-shadow/）
- [ ] ShadowPredictor.__init__ 接收 evidence_store + trace_store 并传透
- [ ] predict() 在 pipeline run 后显式调用 trace_store.save_trace()
- [ ] ShadowPredictor 使用 store_dir 参数（不硬编码 Path.home()）
- [ ] CLI `twin-runtime shadow-run` 和 MCP `twin_shadow_predict` 两种调用路径
- [ ] 低置信度抑制（< 0.4 保持沉默）
- [ ] shadow_log.jsonl JSONL append-only（追加写普通 open，backfill 用 atomic_write）
- [ ] backfill_shadow_log 为独立函数（不依赖 ShadowPredictor 实例）
- [ ] backfill 时自动归档 >90 天记录到 shadow_log.archive.jsonl
- [ ] suppressed prediction（prediction 为空）永远不回填
- [ ] was_correct 回填：cmd_reflect → choice_similarity 比对
- [ ] ConsistencyChecker 冲突在 shadow 中显示
- [ ] `twin-runtime shadow --enable/--disable/--status`
- [ ] ExperienceChangeEntry 作为 C 新增 domain model（Step 0 创建）
- [ ] experience_change_log.jsonl 独立存储 + ExperienceUpdater append
- [ ] compute_trajectory 参数统一为已加载对象（非混合 Path）
- [ ] TrajectoryData 计算正确（rolling CF window_size = max(1, min(10, total//2))）
- [ ] `twin-runtime trajectory --html` 生成带 Chart.js 的报告
- [ ] CF vs Decision Count 图包含 human baseline 标注
- [ ] CF vs Experience Size 图区分 bootstrap vs implicit entries
- [ ] Demo Shadow Mode 段为预录屏幕录像（非实时 Claude Code）
- [ ] Demo 数据通过 prepare_demo_data.py 一次性生成后 git commit
- [ ] Demo 脚本 5 分钟可完整跑通
- [ ] ComparisonExecutor 使用 BaseRunner 实例列表 + executor.load_scenarios()
- [ ] Offline + Online tests 通过
- [ ] **C-α**: 2-3 名外部测试者完成 bootstrap + 20 decisions
- [ ] **C-α**: 至少 1 人 Session 2 CF ≥ 0.7
- [ ] **C-α**: Session 2 vs Session 1 CF delta > 0（flywheel 在转）

---

## C-α: Mini Cross-User Validation（与 C Steps 0-3 并行）

### 目的

在 demo 前用 2-3 个真实用户验证 flywheel 泛化性。如果 CF 在非作者身上也能 >0.7，投资人叙事从 "it works for the creator" 升级为 "it works for real users"。

### 设计

**参与者**：2-3 名友好测试者（熟悉决策类任务、有 Claude Code 使用经验）。

**流程**（每人约 2 小时，分两次完成）：

```
Session 1 (~45 min):
  1. twin-runtime init + bootstrap（~15 min 问答）
  2. 10 个工作决策场景 run + reflect（用测试者自己的真实决策）

Session 2 (~45 min, 隔 1-3 天):
  3. 再做 10 个决策（twin 已从 Session 1 学习）
  4. twin-runtime evaluate → CF 数据
  5. 简短访谈：twin 哪些地方准？哪些离谱？
```

**关键指标**：

| 指标 | 目标 | 意义 |
|------|------|------|
| Session 2 CF | ≥ 0.7 (至少 1 人) | flywheel 可泛化 |
| Session 2 - Session 1 CF delta | > 0 | flywheel 在转 |
| 抽样 5 个决策的定性反馈 | "大致准确" | 质量不是数字噪声 |

**不需要的**：
- 不需要 C 的任何代码（shadow mode, trajectory, demo script）
- 不需要对比 baseline（A/B runner）— 那是 demo 的工作
- 只需要现有的 `bootstrap` + `run` + `reflect` + `evaluate` CLI

### 风险缓解

| 结果 | 行动 |
|------|------|
| CF ≥ 0.7 for 2+ testers | 在 demo 中引用："validated with N=3 external users" |
| CF ≥ 0.7 for 1 tester, others ~0.5-0.6 | 分析低 CF 用户的 domain heads — 可能是 bootstrap 问题而非 pipeline 问题。在 demo 中说 "early cross-user signal" |
| CF < 0.6 for all | 暂停 C3 demo 数据准备，优先修 pipeline（bootstrap 质量？evidence retrieval？head activation prompt？） |

### 数据收集

每个测试者的数据独立存储在 `~/.twin-runtime/store/<user_id>/`。收集：
- 20 个 traces + outcomes（匿名化后可以放在 demo 补充材料中）
- Session 1 vs Session 2 CF 对比（trajectory 数据来源）
- 定性反馈（3-5 句，用于 demo 叙事）

### 时间线

```
Day 1-2: 招募 + Session 1（与 C Step 0-1 并行）
Day 3-4: 间隔期（twin 学习中；C Step 2-3 进行中）
Day 5:   Session 2 + 数据收集（C Step 3 完成时汇合）
Day 6:   分析结果 → 决定是否调整 C Step 4 demo 数据叙事
```

不增加 C 的总工期——完全并行。唯一成本是测试者的 ANTHROPIC_API_KEY 使用（约 $2-5/人）。

---

## C 执行计划

| Step | 内容 | 工期 |
|------|------|------|
| 0 | ExperienceChangeEntry model + JSONL writer in ExperienceUpdater（C2 前置） | 0.5 天 |
| α | **Mini Validation: 招募 + Session 1**（与 Step 0-3 并行，不占主线工期） | — |
| 1 | ShadowPredictor + shadow skill + CLI shadow-run + MCP tool + shadow_log.jsonl | 1.5 天 |
| 2 | TrajectoryData + compute_trajectory + CLI + rolling window 边界 | 1 天 |
| 3 | HTML chart 生成（Chart.js）+ **Validation Session 2 汇合** | 0.5 天 |
| 4 | Demo 数据准备 + DemoRunner + git commit 静态资源（含 validation 结果） | 1 天 |
| 5 | ComparisonExecutor 集成（构造 runner 实例）+ 测试 | 0.5 天 |
| **合计** | | **5 天**（validation 不增加主线工期） |
