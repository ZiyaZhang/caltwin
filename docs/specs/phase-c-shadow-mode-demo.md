# Spec: C — Shadow Mode Demo + Trajectory Visualization

> **Status**: v2（7 corrections applied from review）
> **项目**: twin-runtime
> **前置依赖**: A（A/B Baseline Runner）+ B（Bootstrap Protocol）+ D（Implicit Reflection + OpenClaw Skill）
> **预估工期**: 5-6 天

### Review 修正记录（7 项）

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 1 | 高 | ShadowPredictor._detect_decision 和 Claude Code 重复检测 | 删掉 _detect_decision，接收 question+options 作为输入 |
| 2 | 中 | shadow --status 持久化缺失 | 加 shadow_log.json 文件，TraceStore 中标记 shadow traces |
| 3 | 中 | shadow auto-reflect 触发机制不明 | SKILL.md 明确 Claude Code 在用户选择后主动调 reflect |
| 4 | 低 | ExperienceLogEntry vs ExperienceChangeEntry 命名不一致 | 统一为 ExperienceChangeEntry |
| 5 | 中 | ExperienceChangeLog 存储位置未指定 | 作为 ExperienceLibrary 可选字段 |
| 6 | 低 | C4 ComparisonExecutor 接口适配未检查 | 实施时第一步核对签名，spec 中标注 |
| 7 | 中 | demo 数据生成依赖 flywheel 脚本但不保存快照 | prepare_demo_data.py 自己跑完整流程 |

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
twin-runtime shadow --status     # 显示 shadow 统计（从 shadow_log.json 读取）
```

`shadow --status` 输出（修正 #2：持久化到 shadow_log.json）：

```
Shadow Mode: ENABLED
Session predictions: 12
  Correct: 9 (75%)
  Pending: 2
  Wrong: 1
Silence rate: 3/15 (20% — low confidence suppressed)
```

**shadow_log.json 存储位置**：`~/.twin-runtime/store/<user_id>/shadow_log.json`。每次 shadow prediction 追加一条记录（trace_id, suppressed, timestamp）。reflect 完成后通过 trace_id 回填 was_correct。

### 实现（修正 #1：删掉 _detect_decision，接收 question+options）

```python
# src/twin_runtime/application/shadow/shadow_predictor.py

class ShadowPredictor:
    """
    被动预测器。接收 Claude Code 已提取好的 question + options，
    运行 pipeline 并返回预测。不做二次决策检测（Claude Code LLM 已做）。
    """

    def __init__(self, twin_store, experience_store, llm, user_id: str,
                 shadow_log_path: Optional[Path] = None):
        self._twin_store = twin_store
        self._experience_store = experience_store
        self._llm = llm
        self._user_id = user_id
        self._min_confidence = 0.4
        self._log_path = shadow_log_path or (
            Path.home() / ".twin-runtime" / "store" / user_id / "shadow_log.json"
        )

    def predict(self, question: str, options: List[str]) -> ShadowPrediction:
        """
        输入：Claude Code 提取好的 question + options。
        输出：ShadowPrediction（可能 suppressed=True）。
        不含决策检测——职责在 Claude Code SKILL.md 中。
        """
        from twin_runtime.application.orchestrator.runtime_orchestrator import run
        twin = self._twin_store.load_state(self._user_id)
        exp_lib = self._experience_store.load()

        trace = run(
            query=question,
            option_set=options,
            twin=twin,
            experience_library=exp_lib,
        )

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
        """持久化 shadow prediction 记录（修正 #2）。"""
        import json, tempfile
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = json.loads(self._log_path.read_text()) if self._log_path.exists() else []
        log.append(prediction.model_dump(mode="json"))
        # atomic write
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(self._log_path.parent), suffix=".tmp", delete=False)
        tmp.write(json.dumps(log, indent=2, ensure_ascii=False))
        tmp.close()
        Path(tmp.name).rename(self._log_path)


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
```

### 数据流（修正 #1 #3）

```
用户正常工作
    ↓
Claude Code LLM 检测到决策场景（基于 SKILL.md "When to activate"）
    ↓
Claude Code 提取 question + options
    ↓
调用 twin-runtime run "<question>" -o "<opt1>" "<opt2>" --json
    ↓
ShadowPredictor.predict(question, options)
    ↓ (confidence >= 0.4)
显示 "🔮 Twin prediction: ..."  +  记录到 shadow_log.json
    ↓ (用户做出选择后)
Claude Code 主动调用 twin-runtime reflect --trace-id <id> --choice "<actual>"
```

---

## C2: Fidelity Trajectory Visualization

### 问题

投资人需要**一张图**证明 flywheel 在转。这张图是 demo 的核心视觉证据。

### 两张图

**图 1: CF vs Decision Count（时序轨迹）**

- X 轴：决策序号（1, 2, 3, ...）
- Y 轴：滚动 CF（rolling window = min(10, total/2)）
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
    change_log: List[ExperienceChangeEntry],  # 修正 #4: 统一命名
) -> TrajectoryData:
    """
    从 outcomes + traces + experience change log 计算轨迹数据。
    outcomes 和 traces 通过 trace_id join。
    change_log 记录 ExperienceLibrary 每次变更的时间戳和 size。
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

### 前置改动

**ExperienceLibrary 需要 change log**：每次 add/confirm/supersede 记录一条 ExperienceChangeEntry。这是 C2 图 2 的数据源。

```python
# domain/models/experience.py — 新增（修正 #4 #5）
class ExperienceChangeEntry(BaseModel):
    timestamp: datetime
    action: str          # "add" / "confirm" / "supersede" / "pattern_add"
    entry_id: str
    size_after: int

# 修正 #5: 作为 ExperienceLibrary 的可选字段，随 library 一起序列化
class ExperienceLibrary(BaseModel):
    ...
    change_log: List[ExperienceChangeEntry] = Field(default_factory=list)
```

ExperienceUpdater 的每个 update() 调用后追加一条 ExperienceChangeEntry 到 library.change_log。ExperienceLibraryStore 序列化时自动包含。

---

## C3: Investor Demo Script

### 5 分钟结构

| 时间 | 环节 | 展示内容 | 数据源 |
|------|------|---------|--------|
| 0:00-0:30 | Problem | "AI agents can do tasks, but can they think like you?" | 叙事 |
| 0:30-1:30 | Bootstrap | 实时运行 `twin-runtime bootstrap`（快进版，预录 answers） | B |
| 1:30-2:30 | Shadow Mode | 在 Claude Code 中正常编码，twin 实时预测决策 | C1 |
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
        """展示 3 个 shadow prediction（预录 + 实时混合）。"""
        ...

    def run_comparison_segment(self):
        """展示 A/B Runner 结果（预计算）。"""
        ...

    def run_trajectory_segment(self):
        """展示 trajectory chart（预计算 + 实时更新）。"""
        ...
```

### Demo 数据准备（修正 #7）

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

---

## C4: Mini A/B 升级

### 问题

B 的 `_run_bootstrap_comparison` 是手写 mini comparison，不涉及 baseline（vanilla/persona/rag_persona）。Demo 需要展示 "+20pp over baselines" 的数据。

### 方案

复用 A 的 `ComparisonExecutor`，替换手写 comparison：

```python
# 在 cmd_bootstrap 的末尾：
if not args.no_comparison:
    from twin_runtime.application.comparison.executor import ComparisonExecutor
    executor = ComparisonExecutor(
        runners=["vanilla", "persona", "twin"],
        scenarios=scenarios,
        twin=result.twin,
        experience_library=result.experience_library,
        llm=llm,
    )
    report = executor.run()
    report.print_summary()
```

### 注意（修正 #6）

实施 C4 的**第一步**必须核对 `ComparisonExecutor.__init__` 的当前参数签名与 bootstrap 上下文的匹配度。如果接口不匹配，预留 0.5 天适配。

---

## C 集成点

| 现有模块 | 集成方式 |
|----------|---------|
| A: ComparisonExecutor | C4 复用，替换手写 mini comparison |
| B: ExperienceLibrary | C2 消费 change log 数据 |
| B: Bootstrap | C3 demo 使用预录 answers 快进 |
| D: OutcomeStore | C2 trajectory 的数据源 |
| D: HeartbeatReflector | C1 shadow mode 的 auto-reflect 用同一 API |
| D: ExperienceUpdater | C2 change log 在 updater 中写入 |

---

## C 测试策略

### Offline

```python
# test_shadow/test_shadow_predictor.py
def test_predict_returns_prediction():      # mock pipeline → ShadowPrediction
def test_low_confidence_suppression():      # uncertainty > 0.6 → suppressed=True
def test_shadow_log_persisted():            # predict() → shadow_log.json 有记录
def test_shadow_status_reads_log():         # shadow --status 从 log 统计

# test_visualization/test_trajectory.py
def test_compute_trajectory():              # 10 outcomes → rolling CF
def test_experience_scaling():              # experience size 增长 → CF 提升
def test_bootstrap_phase_marking():         # 前 N 个决策标记为 bootstrap
def test_empty_outcomes():                  # 无数据 → 空 trajectory

# test_demo/test_demo_runner.py
def test_demo_data_integrity():             # demo 数据文件完整性
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
- [ ] ShadowPredictor.predict() 接收 question+options，运行 pipeline
- [ ] 低置信度抑制（< 0.4 保持沉默）
- [ ] shadow_log.json 持久化 + was_correct 回填
- [ ] ConsistencyChecker 冲突在 shadow 中显示
- [ ] `twin-runtime shadow --enable/--disable/--status`
- [ ] ExperienceLibrary.change_log 字段 + ExperienceUpdater 写入
- [ ] TrajectoryData 计算正确（rolling CF + experience scaling）
- [ ] `twin-runtime trajectory --html` 生成带 Chart.js 的报告
- [ ] CF vs Decision Count 图包含 human baseline 标注
- [ ] CF vs Experience Size 图区分 bootstrap vs implicit entries
- [ ] Demo 数据通过 prepare_demo_data.py 生成（自跑完整流程，非依赖 flywheel 脚本）
- [ ] Demo 脚本 5 分钟可完整跑通
- [ ] ComparisonExecutor 替换手写 mini comparison（先核对接口签名）
- [ ] Offline + Online tests 通过

---

## C 执行计划

| Step | 内容 | 工期 |
|------|------|------|
| 0 | ExperienceLibrary change log（C2 前置） | 0.5 天 |
| 1 | ShadowPredictor + shadow skill + CLI + shadow_log | 1.5 天 |
| 2 | TrajectoryData + compute_trajectory + CLI | 1 天 |
| 3 | HTML chart 生成（Chart.js） | 0.5 天 |
| 4 | Demo 数据准备 + DemoRunner | 1 天 |
| 5 | ComparisonExecutor 集成 + 测试 | 0.5 天 |
| **合计** | | **5 天** |
