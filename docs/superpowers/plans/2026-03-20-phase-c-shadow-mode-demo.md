# Plan: C — Shadow Mode Demo + Trajectory Visualization

> **Spec version**: v5 (44-49 corrections)
> **Estimated effort**: 5 days
> **Prerequisites**: A (Baseline Runner) ✅ + B (Bootstrap Protocol) ✅ + D (Implicit Reflection) ✅

### Plan review 修正记录

**Round 1（8 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| C-P1 | 高 | Step 0 ExperienceUpdater 路径错误 `reflection/` | 修正为 `calibration/experience_updater.py` |
| C-P2 | 高 | Step 5 TwinRunner 没有 `experience_library` 参数，构造调用会失败 | Step 5 中扩展 TwinRunner 接受 experience_library |
| C-P3 | 中 | Step 0 给 ExperienceUpdater.__init__ 加 I/O 参数破坏单一职责 | 改为调用方写 change log |
| C-P4 | 中 | ShadowPredictor.predict() 的 trace_store.save_trace 失败应非致命 | try/except + log warning |
| C-P5 | 中 | bootstrap_answers.json 说 20 个回答，但实际 questions.py 有 21 个 | 修正为 21 个 |
| C-P6 | 低 | MCP server 路径错误 `interfaces/mcp/` | 修正为 `server/mcp_server.py` |
| C-P7 | 低 | list_traces() 返回 List[str] 不是 trace 对象，需逐条 load_trace | 明确 list → load 两步 |
| C-P8 | 低 | UpdateResult 命名冲突（experience_updater vs micro_calibration） | 标注风险 |

**Round 2（8 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| C-P9 | 中 | Step 2 list_traces 不传 user_id，依赖 JSON 实现的默认值而非 Protocol | 所有 list_traces 调用统一传 user_id（C 中修，顺带修 D 的 heartbeat） |
| C-P10 | 中 | Step 0 change log 调用方遗漏：_calibration.py:152 和 _implicit.py:243 的 add_pattern() 也需要写 log | 补充完整调用方清单（5 处），标注 add_pattern 两处 |
| C-P11 | 中 | Step 4 bootstrap_answers.json 数量应在 Step 4 开始前从代码验证 | 加验证步骤：`grep -c "BootstrapQuestion(" questions.py` |
| C-P12 | 中 | Step 3 Chart.js CDN 离线时图表不渲染（会议室 WiFi 不稳） | 改为 inline Chart.js min.js 到 HTML template |
| C-P13 | 低 | comparison/trajectory/shadow 段都依赖预计算数据，Step 4 prepare_demo_data.py 是 demo 的单点故障 | 在 Step 4 加 CI schema 验证 + demo dry-run 测试 |
| C-P14 | 低 | Shadow SKILL.md 在 .claude/skills/ 目录，install-skills 不会自动安装 | shadow --enable 同时安装 SKILL.md 到 .claude/skills/ |
| C-P15 | 低 | Plan 没有 CHANGELOG/README 更新步骤 | 每个 Step 末尾加 CHANGELOG entry，Step 5 末尾更新 README |
| C-P16 | — | C-1 "load_scenarios 不存在"是误报 | ComparisonExecutor.load_scenarios() 存在（executor.py:33），无需修正 |

---

## 执行概览

```
Step 0  [0.5d]  ExperienceChangeEntry model + JSONL writer + list_traces user_id 统一
Step 1  [1.5d]  ShadowPredictor + shadow skill + CLI + MCP
Step 2  [1.0d]  TrajectoryData + compute_trajectory + CLI
Step 3  [0.5d]  HTML chart (Chart.js, inline 不依赖 CDN)
Step 4  [1.0d]  Demo 数据准备 + DemoRunner
Step 5  [0.5d]  ComparisonExecutor 集成 + 测试 + CHANGELOG/README
```

---

## Step 0: ExperienceChangeEntry + JSONL Writer (0.5 天)

### 目标

C2 trajectory 需要知道 ExperienceLibrary 在每个时间点的 size。当前 ExperienceUpdater 只更新 library，不记录变更历史。Step 0 添加 change log 基础设施。

### 0.1 新增 ExperienceChangeEntry domain model

**文件**: `src/twin_runtime/domain/models/experience.py`

```python
class ExperienceChangeEntry(BaseModel):
    """ExperienceLibrary 变更审计记录。C 新增 model（D 中不存在）。"""
    timestamp: datetime
    action: str          # "add" / "confirm" / "supersede" / "pattern_add"
    entry_id: str
    size_after: int
```

验证：Phase D 的 `experience.py` 中不存在此 model，这是纯新增。

### 0.2 change log 写入辅助函数

**文件**: `src/twin_runtime/application/calibration/change_log.py`（新建）

```python
def append_change_log(path: Path, entry: ExperienceChangeEntry) -> None:
    """Append 一条 change log 到 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")

def load_change_log(path: Path) -> List[ExperienceChangeEntry]:
    """从 JSONL 文件加载全部 change log。"""
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if line.strip():
            entries.append(ExperienceChangeEntry.model_validate_json(line))
    return entries
```

### 0.3 调用方集成（修正 C-P3：不修改 ExperienceUpdater；修正 C-P10：完整调用方清单）

**不修改** `ExperienceUpdater.__init__` — 它是纯逻辑类，不应引入 I/O 路径参数。`update()` 返回的 `UpdateResult` 已包含 `action` 和 `affected_entry_id`，调用方有足够信息构造 ExperienceChangeEntry。

**完整调用方清单**（修正 C-P10：5 处，含 2 处 add_pattern）：

| # | 文件 | 触发点 | action |
|---|------|--------|--------|
| 1 | `cli/_calibration.py` | cmd_reflect → updater.update() 后 | result.action.value |
| 2 | `application/implicit/heartbeat.py` | _auto_reflect → updater.update() 后 | result.action.value |
| 3 | `cli/_implicit.py` | cmd_confirm accept → updater.update() 后 | result.action.value |
| 4 | `cli/_calibration.py:152` | cmd_reflect → exp_lib.add_pattern(p) 后 | "pattern_add" |
| 5 | `cli/_implicit.py:243` | cmd_mine_patterns → exp_lib.add_pattern(p) 后 | "pattern_add" |

每处模式相同：

```python
result = updater.update(new_entry, library)
# 写 change log
change_log_path = _STORE_DIR / user_id / "experience_change_log.jsonl"
append_change_log(change_log_path, ExperienceChangeEntry(
    timestamp=datetime.now(timezone.utc),
    action=result.action.value,
    entry_id=new_entry.id,
    size_after=library.size,
))
```

add_pattern 处：

```python
exp_lib.add_pattern(p)
append_change_log(change_log_path, ExperienceChangeEntry(
    timestamp=datetime.now(timezone.utc),
    action="pattern_add",
    entry_id=p.id,
    size_after=exp_lib.size,
))
```

### 0.4 list_traces 调用方统一传 user_id（修正 C-P9）

当前所有 `list_traces()` 调用都不传 user_id，依赖 JSON 实现的默认空字符串。Port 签名已有 `user_id=""` 默认值（之前已修复），但最佳实践是显式传入。

在以下调用方补充 `user_id=user_id`：

| 文件 | 行 |
|------|-----|
| `server/mcp_server.py:338` | `trace_store.list_traces(user_id=user_id, limit=limit)` |
| `cli/_calibration.py:146` | `trace_store.list_traces(user_id=user_id, limit=50)` |
| `cli/_calibration.py:215` | `trace_store.list_traces(user_id=user_id, limit=10000)` |
| `cli/_implicit.py:227` | `trace_store.list_traces(user_id=user_id, limit=lookback)` |
| `application/implicit/heartbeat.py:116` | `self._trace_store.list_traces(user_id=self._user_id, limit=200)` |

这确保 E2 SQLite 实现可以按 user_id 过滤。

### 0.5 测试

| 测试 | 断言 |
|------|------|
| `test_append_change_log` | append 后 JSONL 文件新增一行，action 和 size_after 正确 |
| `test_load_change_log` | 3 条 → 加载 3 个 ExperienceChangeEntry |
| `test_load_empty` | 文件不存在 → 返回空列表 |
| `test_updater_not_modified` | ExperienceUpdater.__init__ 签名无 change_log_path 参数 |
| `test_pattern_add_logged` | add_pattern 后 change_log 有 action="pattern_add" 记录 |

### 交付物

- [x] `ExperienceChangeEntry` 在 `domain/models/experience.py`
- [x] `append_change_log()` + `load_change_log()` 在 `calibration/change_log.py`
- [x] 5 处调用方集成（含 2 处 add_pattern）
- [x] 5 处 list_traces 调用补充 user_id
- [x] 5 个 unit tests

---

## Step 1: ShadowPredictor + Shadow Skill + CLI + MCP (1.5 天)

### 目标

实现 C1 的完整 shadow mode：预测 + 日志 + 回填 + CLI 管理 + MCP tool。

### 1.1 ShadowPrediction domain model

**文件**: `src/twin_runtime/domain/models/shadow.py`（新建）

```python
class ShadowPrediction(BaseModel):
    trace_id: str
    question: str = ""
    prediction: str = ""
    confidence: float = 0.0
    consistency_conflict: Optional[str] = None
    suppressed: bool = False
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    was_correct: Optional[bool] = None
```

### 1.2 ShadowPredictor application service

**文件**: `src/twin_runtime/application/shadow/shadow_predictor.py`（新建）

**构造函数参数**（spec #28 #32 #44）：
- `twin_store` — 加载 TwinState
- `experience_store` — 加载 ExperienceLibrary
- `evidence_store` — S2 deliberation 证据检索
- `trace_store` — pipeline 执行后持久化 trace
- `llm` — LLMPort 实例
- `user_id: str`
- `store_dir: Path` — 统一配置路径

**predict(question, options) → ShadowPrediction**：
1. 加载 twin_state 和 experience_library
2. 调用 `orchestrator.run()` 传入全部依赖（含 evidence_store）
3. **try/except** `trace_store.save_trace(trace)`（修正 C-P4：持久化失败非致命，log warning 后继续）
4. 计算 confidence = 1 - trace.uncertainty
5. suppressed = confidence < 0.4
6. 构造 ShadowPrediction，append 到 shadow_log.jsonl
7. 返回

```python
def predict(self, question: str, options: List[str]) -> ShadowPrediction:
    twin = self._twin_store.load_state(self._user_id)
    exp_lib = self._experience_store.load()

    trace = run(
        query=question, option_set=options, twin=twin,
        llm=self._llm, evidence_store=self._evidence_store,
        experience_library=exp_lib,
    )

    # 修正 C-P4: trace 持久化失败非致命
    try:
        self._trace_store.save_trace(trace)
    except Exception:
        logger.warning("Failed to persist shadow trace %s", trace.trace_id)

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
```

**load_log() → List[ShadowPrediction]**：
- 读取 `shadow_log.jsonl` 全部行
- 用于 `shadow --status`

### 1.3 独立 backfill 函数

**文件**: 同上 `shadow_predictor.py` 底部

```python
def backfill_shadow_log(
    log_path: Path,
    trace_id: str,
    was_correct: bool,
    archive_days: int = 90,
) -> None:
```

**逻辑**（spec #45 #46 #49）：
1. 读取 shadow_log.jsonl 全部行
2. 对匹配 trace_id 且 prediction 非空的行，设置 was_correct（suppressed 的跳过）
3. 将 timestamp < 90天前 的行 append 到 `shadow_log.archive.jsonl`
4. 将剩余行 atomic_write 回 `shadow_log.jsonl`

### 1.4 cmd_reflect 集成回填

**文件**: `src/twin_runtime/cli/_calibration.py`

在 `cmd_reflect` 成功执行后新增：

```python
shadow_log_path = _STORE_DIR / user_id / "shadow_log.jsonl"
if shadow_log_path.exists() and args.trace_id:
    from twin_runtime.application.shadow.shadow_predictor import (
        backfill_shadow_log, ShadowPrediction,
    )
    from twin_runtime.application.calibration.fidelity_evaluator import choice_similarity

    # 找到对应 prediction，用 choice_similarity 判断 was_correct
    for line in shadow_log_path.read_text().splitlines():
        if not line.strip():
            continue
        entry = ShadowPrediction.model_validate_json(line)
        if entry.trace_id == args.trace_id and entry.prediction:
            score, rank = choice_similarity([entry.prediction], args.choice)
            backfill_shadow_log(shadow_log_path, args.trace_id, rank == 1)
            break
```

### 1.5 CLI shadow 命令

**文件**: `src/twin_runtime/cli/_shadow.py`（新建）

| 命令 | 功能 |
|------|------|
| `shadow --enable` | 写 config `shadow_mode=true` + 复制 SKILL.md 到 `.claude/skills/twin-shadow/`（修正 C-P14） |
| `shadow --disable` | 写 config `shadow_mode=false`（不删 SKILL.md，用户可手动删） |
| `shadow --status` | 读 shadow_log.jsonl，统计 correct/pending/wrong/silence rate |
| `shadow-run "<q>" -o "A" "B"` | 薄包装：构造 ShadowPredictor → predict() → JSON 输出 |

`shadow-run` 是 CLI 模式的入口。内部构造 ShadowPredictor 并调用 predict()。JSON 输出供 Claude Code SKILL.md 解析。

### 1.6 MCP shadow_predict tool

**文件**: `src/twin_runtime/server/mcp_server.py`（修正 C-P6：正确路径）

新增 tool `twin_shadow_predict`：
- 输入：`{question: str, options: [str]}`
- 内部：构造 ShadowPredictor，调 predict()
- 输出：ShadowPrediction JSON

### 1.7 Claude Code SKILL.md

**文件**: `.claude/skills/twin-shadow/SKILL.md`（新建）

按 spec 中的 SKILL.md 内容创建。核心指令：
- When to activate（2+ options 决策场景）
- Shadow behavior（调 shadow-run / MCP tool）
- After user choice → reflect（闭环）
- Consistency conflict display
- Boundaries（REFUSE/DEGRADE 适用）

### 1.8 测试

| 测试文件 | 测试 | 断言 |
|----------|------|------|
| `test_shadow_predictor.py` | `test_predict_returns_prediction` | mock pipeline → 返回 ShadowPrediction，trace_store.save_trace 被调用 |
| | `test_low_confidence_suppression` | uncertainty=0.7 → suppressed=True, prediction="" |
| | `test_shadow_log_appended` | predict() 后 JSONL 新增一行 |
| | `test_shadow_log_jsonl_format` | 每行是独立 JSON |
| | `test_trace_save_failure_nonfatal` | trace_store.save_trace raises → predict 仍返回结果 + log warning |
| `test_backfill.py` | `test_backfill_was_correct` | 回填后对应行 was_correct=True |
| | `test_backfill_missing_trace_id` | 不存在的 ID → no-op |
| | `test_backfill_suppressed_skipped` | suppressed entry → was_correct 保持 None |
| | `test_backfill_archives_old_entries` | >90天的行转移到 archive 文件 |
| `test_shadow_cli.py` | `test_shadow_status` | 读 log 统计正确 |
| | `test_shadow_enable_disable` | config 正确写入 |

### 交付物

- [x] `ShadowPrediction` model
- [x] `ShadowPredictor` class（含 trace_store 持久化 + failure tolerance）
- [x] `backfill_shadow_log()` 独立函数
- [x] `cmd_reflect` 回填集成
- [x] CLI `shadow` + `shadow-run` 命令
- [x] MCP `twin_shadow_predict` tool（在 `server/mcp_server.py` 中）
- [x] `.claude/skills/twin-shadow/SKILL.md`
- [x] 11 个 unit tests

---

## Step 2: TrajectoryData + compute_trajectory + CLI (1.0 天)

### 目标

实现 C2 的数据计算层：从 outcomes + traces + change log 计算 fidelity 轨迹。

### 2.1 TrajectoryData / DecisionPoint models

**文件**: `src/twin_runtime/application/visualization/trajectory.py`（新建）

```python
class DecisionPoint(BaseModel):
    index: int
    trace_id: str
    was_correct: bool
    confidence: float
    source: str
    experience_size_at_time: int
    timestamp: datetime

class TrajectoryData(BaseModel):
    decisions: List[DecisionPoint]
    rolling_cf: List[float]
    window_size: int
    experience_sizes: List[int]
    bootstrap_count: int
    human_baseline: float = 0.85
```

### 2.2 compute_trajectory 函数

**签名**（spec #47：统一为已加载对象）：

```python
def compute_trajectory(
    outcomes: List[OutcomeRecord],
    traces: List[RuntimeDecisionTrace],
    change_log: List[ExperienceChangeEntry],
) -> TrajectoryData:
```

**算法**：

1. **Join**：outcomes 和 traces 通过 trace_id 关联，按 timestamp 排序
2. **Experience size at time**：遍历 change_log（已按 timestamp 排序），对每个 decision point 找到对应时间的 size_after
3. **Rolling CF**：
   - `window_size = max(1, min(10, len(decisions) // 2))`
   - 对每个 index i，计算 `decisions[max(0, i-window+1):i+1]` 中 was_correct=True 的比例
4. **Bootstrap count**：找到第一个 `source != "user_correction"` 或 timestamp 超过 bootstrap 结束时间的 decision，之前的都是 bootstrap 阶段

### 2.3 CLI trajectory 命令

**文件**: `src/twin_runtime/cli/_visualization.py`（新建）

```
twin-runtime trajectory [--format json|csv|html] [--output path] [--open]
```

- 默认 `--format json`，stdout 输出
- `--format html` 委托给 Step 3 的 HTML generator
- `--open` 搭配 html 格式，生成后 `webbrowser.open()`

**数据加载流程**（修正 C-P7：list→load 两步；修正 C-P9：传 user_id）：
1. `outcome_store.list_outcomes(limit=500)` → outcomes
2. 从 outcomes 提取 `needed_trace_ids = {o.trace_id for o in outcomes}`
3. `traces = [trace_store.load_trace(tid) for tid in needed_trace_ids]`（只加载有 outcome 的 traces，避免全量加载）
4. `change_log = load_change_log(store_dir / user_id / "experience_change_log.jsonl")`
5. `compute_trajectory(outcomes, traces, change_log)` → TrajectoryData
6. 输出 JSON / CSV / 传给 HTML generator

### 2.4 测试

| 测试 | 断言 |
|------|------|
| `test_compute_trajectory_basic` | 10 outcomes → 10 rolling CF 值，单调递增（如果后面全对） |
| `test_experience_scaling` | experience size 随 change_log 增长 |
| `test_bootstrap_phase_marking` | bootstrap_count 正确标记 |
| `test_empty_outcomes` | 空输入 → 空 TrajectoryData |
| `test_rolling_window_boundary_1` | total=1 → window_size=1（不是 0） |
| `test_rolling_window_boundary_2` | total=3 → window_size=1（min(10, 1)） |
| `test_rolling_window_normal` | total=30 → window_size=10 |

### 交付物

- [x] `DecisionPoint` + `TrajectoryData` models
- [x] `compute_trajectory()` 函数
- [x] CLI `trajectory` 命令（含 list → load 两步加载）
- [x] 7 个 unit tests

---

## Step 3: HTML Chart 生成 (0.5 天)

### 目标

用 Chart.js 生成自包含 HTML 报告，含两张图。

### 3.1 HTML template

**文件**: `src/twin_runtime/application/visualization/chart_template.html`

单文件自包含 HTML（修正 C-P12：inline Chart.js，不依赖 CDN。会议室 WiFi 不稳时仍能渲染）：

```html
<!DOCTYPE html>
<html>
<head>
  <title>twin-runtime Fidelity Trajectory</title>
  <!-- Chart.js min.js inline（~200KB），确保离线可用 -->
  <script>__CHARTJS_INLINE__</script>
</head>
<body>
  <h1>Choice Fidelity Trajectory</h1>

  <!-- 图 1: CF vs Decision Count -->
  <canvas id="cfTimeline"></canvas>

  <!-- 图 2: CF vs Experience Library Size -->
  <canvas id="cfExperience"></canvas>

  <script>
    const data = __TRAJECTORY_DATA__;  // 占位符，Python 替换

    // 图 1 配置
    // - X: decision index
    // - Y: rolling CF
    // - 灰色背景: bootstrap 阶段
    // - 虚线: human baseline 0.85

    // 图 2 配置
    // - X: experience_sizes
    // - Y: rolling_cf
    // - 颜色区分: bootstrap entries (灰) vs implicit entries (蓝)
  </script>
</body>
</html>
```

### 3.2 generate_html 函数

**文件**: `src/twin_runtime/application/visualization/trajectory.py`

```python
_CHARTJS_MIN = (Path(__file__).parent / "chart.min.js").read_text()

def generate_html(trajectory: TrajectoryData, output_path: Path) -> Path:
    """将 TrajectoryData + Chart.js 注入 HTML template，写到 output_path。

    自包含：无外部 CDN 依赖（修正 C-P12）。
    """
    template = (Path(__file__).parent / "chart_template.html").read_text()
    data_json = trajectory.model_dump_json()
    html = (template
            .replace("__CHARTJS_INLINE__", _CHARTJS_MIN)
            .replace("__TRAJECTORY_DATA__", data_json))
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

**Chart.js 本地文件**：`src/twin_runtime/application/visualization/chart.min.js` — 从 `https://cdn.jsdelivr.net/npm/chart.js` 下载一次，git commit 为静态资源（~200KB）。

### 3.3 图表细节

**图 1: CF vs Decision Count**
- Line chart
- X labels: 1, 2, 3, ... (decision index)
- Y: rolling_cf (0.0-1.0)
- 灰色矩形标注 bootstrap 阶段（前 bootstrap_count 个 decisions）
- 水平虚线 at 0.85，标签 "Human test-retest baseline"
- 工具提示显示 trace_id + source

**图 2: CF vs Experience Size**
- Scatter chart
- X: experience_sizes[i]
- Y: rolling_cf[i]
- 点颜色：bootstrap entries (灰色) vs implicit entries (蓝色)，通过 `i < bootstrap_count` 区分

### 3.4 测试

| 测试 | 断言 |
|------|------|
| `test_generate_html_valid` | 生成的 HTML 包含 Chart.js script 和 __TRAJECTORY_DATA__ 替换后的 JSON |
| `test_html_contains_both_charts` | 包含 cfTimeline 和 cfExperience canvas |

### 交付物

- [x] `chart_template.html`
- [x] `generate_html()` 函数
- [x] CLI `--format html` + `--open` 集成
- [x] 2 个 unit tests

---

## Step 4: Demo 数据准备 + DemoRunner (1.0 天)

### 目标

生成可重复的 demo 数据 + 编写 investor demo 脚本。

### 4.1 prepare_demo_data.py

**文件**: `scripts/prepare_demo_data.py`

**流程**：
1. 初始化 twin store（固定 user_id = "demo_user"）
2. 运行 bootstrap（预定义 answers JSON）
3. 保存 snapshot: `demo/sample_twin_state.json` + `demo/sample_experience_library.json`
4. 循环 50+ 次：run → record_outcome（固定 ground truth）→ reflect
5. 每步保存 outcome + trace → 最终生成 `demo/trajectory_data.json`
6. 在 bootstrap 后运行一次 ComparisonExecutor → `demo/comparison_results.json`
7. 生成 5 个 shadow 场景 → `demo/shadow_scenarios.json`

**关键约束**：
- 需要 `ANTHROPIC_API_KEY`
- 一次性运行，输出 git commit 为静态资源
- 估计 API 费用：~$1-3（50 轮 × ~5 LLM calls × Sonnet）

### 4.2 demo/ 目录结构

```
demo/
├── bootstrap_answers.json          # 21 个预录回答（修正 C-P5：与实际 questions.py 对齐）
├── shadow_scenarios.json           # 5 个 shadow mode 场景 + ground truth
├── comparison_results.json         # 4 runner CF 对比
├── trajectory_data.json            # TrajectoryData JSON
├── sample_twin_state.json          # bootstrap 后的 TwinState
├── sample_experience_library.json  # 50+ entries 的 ExperienceLibrary
└── shadow_recording/               # Shadow Mode 预录屏幕录像（手动制作）
    └── README.md                   # 录制说明
```

### 4.3 DemoRunner

**文件**: `scripts/investor_demo.py`

```python
class DemoRunner:
    def __init__(self, demo_dir: str = "demo/"):
        self.demo_dir = Path(demo_dir)
        # 加载所有预计算数据
        ...

    def run_bootstrap_segment(self):
        """0:30-1:30 — 快进 bootstrap（注入预录 answers）。"""
        # 实时调 bootstrap engine，但用预录 answers 跳过交互
        ...

    def run_shadow_segment(self):
        """1:30-2:30 — 预录屏幕录像。
        DemoRunner 不调 LLM，仅播放/展示预录的 shadow 场景结果。
        实时 Claude Code 会话有 LLM 延迟风险，不适合 5 分钟限时 demo。
        """
        for scenario in self.shadow_scenarios:
            print(f"  🔮 Prediction: {scenario['prediction']} "
                  f"(confidence: {scenario['confidence']:.0%})")
            print(f"  ✅ Actual: {scenario['actual']}")
            ...

    def run_comparison_segment(self):
        """2:30-3:30 — 展示预计算的 A/B 对比。"""
        ...

    def run_trajectory_segment(self):
        """3:30-4:30 — 展示 trajectory chart。"""
        ...

    def run_full_demo(self):
        """5 分钟完整 demo。"""
        self.run_bootstrap_segment()
        self.run_shadow_segment()
        self.run_comparison_segment()
        self.run_trajectory_segment()
```

### 4.4 bootstrap_answers.json 设计（修正 C-P5 C-P11）

**Step 4 第一步**（修正 C-P11）：验证实际 question 数量：
```bash
grep -c "BootstrapQuestion(" src/twin_runtime/application/bootstrap/questions.py
# 预期：21（Phase 1: 12, Phase 2: 6, Phase 3: 3）
```

如果数量与上次检查（21）不同，调整 answers 数量。

**21 个回答**，与 `bootstrap/questions.py` 中的 `DEFAULT_QUESTIONS` 一一对应：
- Phase 1: 12 forced-choice（覆盖 risk_tolerance ×3, action_threshold ×3, information_threshold ×2, conflict_style ×2, explore_exploit ×2）
- Phase 2: 6 domain self-assessment（work, finance, health, relationships, learning + 1 spare）
- Phase 3: 3 open-ended scenario narratives

### 4.5 CI 验证（修正 C-P13：demo 数据是单点故障，需充分验证）

**不在 CI 中重新生成 demo 数据**。CI 验证：

```python
def test_demo_files_exist():
    required = [
        "bootstrap_answers.json", "shadow_scenarios.json",
        "comparison_results.json", "trajectory_data.json",
        "sample_twin_state.json", "sample_experience_library.json",
    ]
    for f in required:
        assert (Path("demo") / f).exists()

def test_demo_data_schema():
    """验证 demo 数据文件 schema 正确。"""
    TwinState.model_validate_json(Path("demo/sample_twin_state.json").read_text())
    ExperienceLibrary.model_validate_json(Path("demo/sample_experience_library.json").read_text())
    TrajectoryData.model_validate_json(Path("demo/trajectory_data.json").read_text())
    ...

def test_demo_dry_run():
    """DemoRunner 能不调 LLM 完整跑通（所有预计算数据加载成功）。"""
    runner = DemoRunner()
    # 每个 segment 的 _load 不抛异常
    runner.run_comparison_segment()
    runner.run_trajectory_segment()
```

**bootstrap_answers.json 数量一致性检查**（在 test_demo_data_schema 中）：
```python
def test_bootstrap_answers_count():
    answers = json.loads(Path("demo/bootstrap_answers.json").read_text())
    from twin_runtime.application.bootstrap.questions import DEFAULT_QUESTIONS
    assert len(answers) == len(DEFAULT_QUESTIONS)
```

### 交付物

- [x] `scripts/prepare_demo_data.py`
- [x] `demo/bootstrap_answers.json`（21 个回答，与 questions.py 对齐）
- [x] `scripts/investor_demo.py` + `DemoRunner`
- [x] `demo/shadow_recording/README.md`（录制指南）
- [x] CI schema 验证 tests
- [x] 运行 prepare_demo_data.py 并 git commit 静态资源

---

## Step 5: ComparisonExecutor 集成 + 测试 (0.5 天)

### 目标

用 A 的 ComparisonExecutor 替换 B 的手写 mini comparison。

### 5.1 验证 Runner 构造函数签名（修正 C-P2）

**实际签名**（从代码验证）：

```python
VanillaRunner.__init__(llm: LLMPort)
PersonaRunner.__init__(llm: LLMPort)
TwinRunner.__init__(llm: Optional[LLMPort] = None, evidence_store: Optional[JsonFileEvidenceStore] = None)
# 注意：TwinRunner 没有 experience_library 参数！
```

**问题**：TwinRunner 内部调 `pipeline.runner.run()` 只传 `llm` 和 `evidence_store`，不传 `experience_library`。这意味着 comparison 中 twin runner 的 ConsistencyChecker 和 S2 deliberation 无法使用 experience context，CF 可能偏低。

**两个选择**：
- **选项 A（推荐）**：在 Step 5 中扩展 TwinRunner 接受 `experience_library` 参数，传透给 `orchestrator.run()`。改动量小（加一个参数 + 传透）。
- **选项 B**：暂不改，用当前 TwinRunner 的 CF 作为 baseline。demo 中说明 "without experience context" 的数据。

**执行选项 A**：

```python
# twin_runner.py 修改
class TwinRunner(BaseRunner):
    def __init__(self, llm=None, evidence_store=None, experience_library=None):
        self._llm = llm
        self._evidence_store = evidence_store
        self._experience_library = experience_library

    def run_scenario(self, scenario, twin):
        from twin_runtime.application.orchestrator.runtime_orchestrator import run
        trace = run(
            query=scenario.query, option_set=scenario.options, twin=twin,
            llm=self._llm, evidence_store=self._evidence_store,
            experience_library=self._experience_library,
        )
        ...
```

### 5.2 集成到 cmd_bootstrap

**文件**: `src/twin_runtime/cli/_onboarding.py`

在 bootstrap 完成后：

```python
if not args.no_comparison:
    runners = [
        VanillaRunner(llm=llm),
        PersonaRunner(llm=llm),
        TwinRunner(llm=llm, evidence_store=evidence_store,
                   experience_library=result.experience_library),
    ]
    executor = ComparisonExecutor(runners=runners, twin=result.twin)
    scenario_set = executor.load_scenarios(Path("data/comparison_scenarios.json"))
    report = executor.run_all(scenario_set)
    for rid, agg in report.aggregates.items():
        print(f"  {rid}: CF={agg.cf_score:.2f}")
```

### 5.3 comparison_scenarios.json

**文件**: `data/comparison_scenarios.json`

包含 10-15 个带 ground_truth 的场景，覆盖 work domain 常见决策类型。格式与 A 的 ScenarioSet 对齐。

### 5.4 测试

| 测试 | 断言 |
|------|------|
| `test_twin_runner_accepts_experience_library` | 构造 TwinRunner(experience_library=lib) 不报错 |
| `test_comparison_executor_integration` | mock runners → ComparisonReport 正确生成 |
| `test_comparison_scenarios_valid` | data/comparison_scenarios.json 通过 ScenarioSet 校验 |

### 5.5 文档更新（修正 C-P15）

- CHANGELOG.md：Phase C section（Shadow Mode, Trajectory, Demo, ComparisonExecutor 集成）
- README.md：更新 "Features" section 加 Shadow Mode + Trajectory CLI

### 交付物

- [x] TwinRunner 扩展：接受 `experience_library` 参数
- [x] cmd_bootstrap 集成 ComparisonExecutor
- [x] `data/comparison_scenarios.json`
- [x] CHANGELOG + README 更新
- [x] 3 个 tests

---

## 全局测试策略

### Offline tests 汇总

```
tests/
├── test_change_log/
│   └── test_experience_change_log.py   # Step 0: 5 tests
├── test_shadow/
│   ├── test_shadow_predictor.py        # Step 1: 5 tests
│   ├── test_backfill.py                # Step 1: 4 tests
│   └── test_shadow_cli.py             # Step 1: 2 tests
├── test_visualization/
│   ├── test_trajectory.py              # Step 2: 7 tests
│   └── test_html_chart.py             # Step 3: 2 tests
├── test_demo/
│   ├── test_demo_data_integrity.py    # Step 4: 4 tests (含 dry-run + answers count)
│   └── test_comparison_integration.py  # Step 5: 3 tests
```

**总计**: ~32 个 offline tests

### Online tests

```python
@pytest.mark.requires_llm
def test_shadow_end_to_end(): ...
def test_trajectory_html_generation(): ...
```

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| orchestrator.run() 签名与 ShadowPredictor 预期不匹配 | Step 1 阻塞 | Step 1.2 第一步验证签名 |
| TwinRunner experience_library 扩展影响现有 comparison tests | Step 5 返工 | 新参数默认 None，向后兼容 |
| prepare_demo_data.py LLM 费用超预期 | Step 4 预算 | 先用 10 轮验证费用 |
| shadow_log.jsonl 在高频 shadow mode 下增长过快 | 长期稳定性 | 90 天归档策略 |
| UpdateResult 命名冲突 | 未来集成风险 | C-P8：当前不触发，实施时注意 import 路径 |

---

## 里程碑

| 日 | 完成 Step | 可验证产出 |
|----|-----------|-----------|
| Day 1 | Step 0 + Step 1 (1/2) | ExperienceChangeEntry + change log 5 处集成 + list_traces user_id 统一 + ShadowPredictor 可预测 |
| Day 2 | Step 1 (2/2) | shadow CLI + MCP + 回填 + SKILL.md + 11 tests 通过 |
| Day 3 | Step 2 | trajectory CLI 输出 JSON + 7 tests 通过 |
| Day 4 前半 | Step 3 | HTML 报告可在浏览器离线打开（inline Chart.js） |
| Day 4 后半 + Day 5 前半 | Step 4 | demo 数据生成 + DemoRunner dry-run 通过 |
| Day 5 后半 | Step 5 | TwinRunner 扩展 + ComparisonExecutor 集成 + CHANGELOG/README + ~32 tests 通过 |
