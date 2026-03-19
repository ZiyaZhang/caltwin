# Plan: D — Implicit Reflection + OpenClaw Skill (Implementation v3)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans.
> **对应 Spec**: docs/specs/phase-d-implicit-reflection.md
> **总步骤**: 8 步 / 8 天
> **依赖**: B 完成 + 5 项前置改动
>
> **NOTE (v3)**: CLI 已拆分为 `src/twin_runtime/cli/` 包（9 个子模块）。所有 CLI 改动需定位到具体子模块，不再是单个 cli.py。

---

## Step 0: 前置改动（5 项，1 天）

### 0a. RuntimeDecisionTrace 加 option_set

**文件**: `src/twin_runtime/domain/models/runtime.py`
- 在 `shadow_scores` 之后、`consistency_check_passed` 之前加：
```python
option_set: List[str] = Field(default_factory=list, description="Options evaluated in this decision")
```

**文件**: `src/twin_runtime/application/orchestrator/runtime_orchestrator.py`
- S1 路径（~line 65 之后）和 S2 路径（~line 75 之后）、FORCE_DEGRADE 之前加：
```python
trace.option_set = option_set
```

**测试**: 现有 tests 不 break（default_factory）。新增 1 test 验证 option_set 被填充。

### 0b. OutcomeSource 扩展

**文件**: `src/twin_runtime/domain/models/primitives.py`
- OutcomeSource 新增 4 值：IMPLICIT_GIT, IMPLICIT_FILE, IMPLICIT_CALENDAR, IMPLICIT_EMAIL

**测试**: 序列化/反序列化验证。

### 0c. reflect CLI 加 --source / --confidence

**文件**: `src/twin_runtime/cli/_main.py` (argparse 定义)
1. 在 `p_reflect` 定义后加：
```python
p_reflect.add_argument("--source", default="user_correction",
    choices=[s.value for s in OutcomeSource])
p_reflect.add_argument("--confidence", type=float, default=0.8)
```

**文件**: `src/twin_runtime/cli/_calibration.py` (cmd_reflect 实现)
2. cmd_reflect 中 `OutcomeSource(args.source)` 传入 record_outcome 的 source 参数
3. **P1: confidence 不传入 record_outcome**，仅在输出提示中显示

**测试**: 参数解析 + mock cmd_reflect。

### 0d. extract_keywords 提升为公共 util

**创建目录**:
```bash
mkdir -p src/twin_runtime/domain/utils/
touch src/twin_runtime/domain/utils/__init__.py
```

**新文件**: `src/twin_runtime/domain/utils/text.py`
- 从 `memory_access_planner._extract_keywords()` 拷贝
- 改名为 `extract_keywords()`（去掉下划线前缀）
- 加 type hints + docstring + `max_keywords` 参数

**改动 3 个消费方** (HeartbeatReflector 在 Step 2 新建时直接引用):
- `application/planner/memory_access_planner.py`: `from twin_runtime.domain.utils.text import extract_keywords`
- `application/calibration/reflection_generator.py`: 同上
- `application/pipeline/consistency_checker.py`: 同上

**测试**: 现有 tests 全绿 + 新增 `tests/test_utils_text.py`（中英文、CJK bigram、空输入）。

### 0e. ExperienceLibrary 加 add_pattern()

**文件**: `src/twin_runtime/domain/models/experience.py`
```python
def add_pattern(self, pattern: PatternInsight) -> None:
    """Add a PatternInsight to the library."""
    self.patterns.append(pattern)  # I3: 用 self.patterns 非 self._patterns
```

**测试**: add_pattern 后 library.patterns 和 library.size 正确。

### 0 验收

```bash
pytest -q -m "not requires_llm"   # 全绿，无回归
ruff check src/ tests/
```

Commit: `feat: D prerequisites — option_set, OutcomeSource, reflect params, extract_keywords, add_pattern`

---

## Step 1: ExperienceUpdater (D3)（1 天）

先做 D3，因为 D2 的 `_auto_reflect` 依赖它。

### 新文件

`src/twin_runtime/application/calibration/experience_updater.py`

- `UpdateAction(str, Enum)`: ADDED / CONFIRMED / SUPERSEDED / REJECTED
- `UpdateResult(BaseModel)`: action, reason, affected_entry_id
- `ExperienceUpdater`:
  - `update(new_entry: ExperienceEntry, library: ExperienceLibrary) -> UpdateResult`
  - `_is_duplicate()`: Jaccard(scenario_type) > 0.6 && keyword_overlap(insight) > 0.5
  - `_is_conflicting()`: same scenario + different was_correct → preference drift

### 集成

**文件**: `src/twin_runtime/cli/_calibration.py` (cmd_reflect)

ReflectionGenerator 之后:
```python
# 替换 exp_lib.add(reflection.new_entry)
from twin_runtime.application.calibration.experience_updater import ExperienceUpdater
updater = ExperienceUpdater()
result = updater.update(reflection.new_entry, exp_lib)
print(f"  [{result.action.value}] {result.reason}")
```

### 测试

`tests/test_implicit/test_experience_updater.py`:
- test_add_new_scenario: 空 library → ADDED
- test_duplicate_confirmed: 高 overlap → CONFIRMED, count++
- test_conflict_superseded: same scenario, diff was_correct → SUPERSEDED, weight*0.5
- test_complementary_added: same domain, diff angle → ADDED
- test_integration_with_reflect: mock ReflectionGenerator → updater → verify library

Commit: `feat(D3): ExperienceUpdater — conflict-aware experience gating`

---

## Step 2: HeartbeatReflector 核心 (D2)（2 天）

### 新文件

```
src/twin_runtime/application/implicit/__init__.py
src/twin_runtime/application/implicit/heartbeat.py
```

- `InferredReflection(BaseModel)`: trace_id, inferred_choice, confidence, signal_source (OutcomeSource), evidence_summary
- `HeartbeatReport(BaseModel)`: inferred, auto_reflected, queued, errors
- `HeartbeatReflector`:
  - `__init__(trace_store, calibration_store, twin_store, experience_store, llm, user_id, auto_reflect_threshold=0.7, pending_queue_path=None, calendar_adapter=None, gmail_adapter=None)`
  - `run() -> HeartbeatReport`
  - `_find_pending_traces()`:
    ```python
    all_ids = self._trace_store.list_traces(limit=200)
    reflected_ids = {o.trace_id for o in self._calibration_store.list_outcomes()}
    pending = []
    for tid in all_ids:
        if tid not in reflected_ids:
            trace = self._trace_store.load_trace(tid)
            if trace.option_set:
                pending.append(trace)
    return pending
    ```
  - `_infer_from_git_commits(pending)`: subprocess git log → keyword match via extract_keywords()
  - `_infer_from_git_prs(pending)`: subprocess git log --merges → higher confidence
  - `_infer_from_file_changes(pending)`: find -mtime -1 → low confidence
  - `_infer_from_calendar(pending)`: **I2: adapter.scan(since=now-24h)** → keyword match → 0.4-0.7
  - `_infer_from_email(pending)`: **I2: adapter.scan(since=now-24h)** → sent mail keywords → 0.3-0.6
  - `_dedup(inferences)`: per trace_id 保留最高 confidence
  - `_auto_reflect(inf)`: **I1 完整签名**:
    ```python
    trace = self._trace_store.load_trace(inf.trace_id)
    twin = self._twin_store.load_state(self._user_id)
    exp_lib = self._experience_store.load()
    outcome, update = record_outcome(
        trace_id=inf.trace_id,
        actual_choice=inf.inferred_choice,
        source=inf.signal_source,       # OutcomeSource.IMPLICIT_GIT etc.
        twin=twin,
        trace_store=self._trace_store,
        calibration_store=self._calibration_store,
    )
    reflection = ReflectionGenerator(self._llm).process(trace, inf.inferred_choice, exp_lib)
    if reflection.new_entry:
        ExperienceUpdater().update(reflection.new_entry, exp_lib)
    self._experience_store.save(exp_lib)
    ```
  - `_queue_for_confirmation(inf)`: atomic write (tmpfile + os.rename)

### 测试

`tests/test_implicit/test_heartbeat.py`:
- test_pending_via_diff: 3 traces, 1 outcome → 2 pending
- test_pending_loads_trace_objects: 逐个 load 验证 option_set
- test_no_pending: all reflected → empty report
- test_git_commit_match: mock subprocess → correct inference
- test_git_pr_higher_confidence: merge → confidence > commit
- test_file_change_low_confidence: file → confidence < 0.5
- test_calendar_inference: mock CalendarAdapter.scan() → keyword match
- test_email_inference: mock GmailAdapter.scan() → sent mail match
- test_calendar_not_configured: no adapter → graceful skip
- test_email_not_configured: no adapter → graceful skip
- test_dedup_keeps_highest: same trace, multiple signals → keep highest
- test_auto_reflect_above_threshold: 0.8 → auto_reflected++
- test_auto_reflect_record_outcome_signature: verify twin, trace_store, calibration_store passed (I1)
- test_queue_below_threshold: 0.4 → queued++
- test_queue_atomic_write: verify tmpfile + rename
- test_no_git_available: subprocess fails → graceful empty

Commit: `feat(D2): HeartbeatReflector — implicit reflection from Git/Calendar/Email/file signals`

---

## Step 3: CLI heartbeat + confirm（1 天）

### 新文件: `src/twin_runtime/cli/_implicit.py`

New CLI submodule for heartbeat + confirm commands (matches CLI split pattern).

```python
# src/twin_runtime/cli/_implicit.py

def cmd_heartbeat(args):
    from twin_runtime.cli._main import _load_config, _apply_env, _STORE_DIR
    config = _load_config()
    _apply_env(config)
    user_id = config.get("user_id", "default")

    trace_store = JsonFileTraceStore(str(_STORE_DIR / user_id / "traces"))
    cal_store = CalibrationStore(str(_STORE_DIR), user_id)
    twin_store = TwinStore(str(_STORE_DIR))
    exp_store = ExperienceLibraryStore(str(_STORE_DIR), user_id)
    llm = DefaultLLM()

    # Optional adapters
    calendar_adapter = gmail_adapter = None
    if config.get("google_credentials"):
        try:
            from twin_runtime.infrastructure.sources.calendar_adapter import CalendarAdapter
            from twin_runtime.infrastructure.sources.gmail_adapter import GmailAdapter
            calendar_adapter = CalendarAdapter(credentials_path=config["google_credentials"])
            gmail_adapter = GmailAdapter(credentials_path=config["google_credentials"])
        except ImportError:
            pass

    reflector = HeartbeatReflector(
        trace_store=trace_store, calibration_store=cal_store,
        twin_store=twin_store, experience_store=exp_store,
        llm=llm, user_id=user_id,
        calendar_adapter=calendar_adapter, gmail_adapter=gmail_adapter,
    )
    report = reflector.run()
    print(f"Heartbeat: {report.inferred} inferred, "
          f"{report.auto_reflected} auto-reflected, {report.queued} queued")


def cmd_confirm(args):
    # --list: print pending queue
    # --accept-all: auto-reflect each pending
    # default: interactive Y/N per item
```

### argparse 定义

**文件**: `src/twin_runtime/cli/_main.py` — 在现有 subparsers 之后加:

```python
# heartbeat + confirm (Phase D)
sub.add_parser("heartbeat", help="Run implicit reflection from local signals")
p_confirm = sub.add_parser("confirm", help="Confirm pending implicit reflections")
p_confirm.add_argument("--list", action="store_true", dest="list_only")
p_confirm.add_argument("--accept-all", action="store_true")
```

**文件**: `src/twin_runtime/cli/_main.py` — commands dict 中加:

```python
"heartbeat": cmd_heartbeat,
"confirm": cmd_confirm,
```

### 测试

`tests/test_implicit/test_cli_heartbeat.py`:
- test_heartbeat_argparse
- test_heartbeat_mock_stores: mock all → verify report output
- test_confirm_list: mock pending → verify list output
- test_confirm_accept_all: mock pending → verify all processed
- test_confirm_empty_queue: no pending → friendly message

Commit: `feat(D2): CLI heartbeat + confirm commands`

---

## Step 4: HardCaseMiner (D4)（1.5 天）

### 新文件

`src/twin_runtime/application/calibration/hard_case_miner.py`

- `HardCaseMiner(llm: LLMPort, min_failures=3)`
- `mine(traces: List[RuntimeDecisionTrace], outcomes: List[OutcomeRecord]) -> List[PatternInsight]`
  - Join traces + outcomes by trace_id → filter failures (prediction_rank != 1)
  - **P2: 独立分组** (defaultdict by domain from outcome.domain)
  - Each group ≥ 2 failures → `_analyze_group(domain, group)` → `self._llm.ask_json()` (#5)
  - → PatternInsight (weight=2.0)

### 触发 (P8: 文件计数器)

**文件**: `src/twin_runtime/cli/_calibration.py` — 新增 helper:

```python
def _increment_reflect_counter(user_id: str) -> int:
    from twin_runtime.cli._main import _STORE_DIR
    counter_path = _STORE_DIR / user_id / "reflect_count"
    count = int(counter_path.read_text()) if counter_path.exists() else 0
    count += 1
    counter_path.write_text(str(count))
    return count
```

**文件**: `src/twin_runtime/cli/_calibration.py` — cmd_reflect 末尾集成:

```python
count = _increment_reflect_counter(user_id)
if count >= 20:
    miner = HardCaseMiner(llm)
    trace_ids = trace_store.list_traces(limit=50)
    traces = [trace_store.load_trace(tid) for tid in trace_ids]
    outcomes = cal_store.list_outcomes()
    patterns = miner.mine(traces, outcomes)
    for p in patterns:
        exp_lib.add_pattern(p)  # P3, I3
    if patterns:
        exp_store.save(exp_lib)
        print(f"  Pattern mining: found {len(patterns)} patterns")
    (_STORE_DIR / user_id / "reflect_count").write_text("0")
```

### CLI

**文件**: `src/twin_runtime/cli/_main.py` — argparse:

```python
# mine-patterns (Phase D)
p_mine = sub.add_parser("mine-patterns", help="Analyze failure patterns")
p_mine.add_argument("--min-failures", type=int, default=3)
p_mine.add_argument("--lookback", type=int, default=50)
```

**文件**: `src/twin_runtime/cli/_implicit.py` — cmd_mine_patterns 实现

### 测试

`tests/test_implicit/test_hard_case_miner.py`:
- test_insufficient_failures: 2 < 3 → empty
- test_group_by_domain: P2 独立分组正确
- test_single_domain_pattern: mock LLM → PatternInsight 字段完整
- test_uses_llm_port_ask_json: #5 验证
- test_weight_is_2: weight == 2.0
- test_counter_increment: P8 文件 +1
- test_counter_triggers_at_20: P8 count=20 → mine 触发
- test_counter_resets_after_mine: P8 归零
- test_counter_no_skip: 19→20→21 逐个+1 不跳过

Commit: `feat(D4): HardCaseMiner — systematic failure pattern detection`

---

## Step 5: OpenClaw Skill (D1)（0.5 天）

### 新文件

```
skills/openclaw/caltwin/SKILL.md
skills/openclaw/caltwin/scripts/heartbeat_reflect.py
skills/openclaw/caltwin/scripts/install_check.sh
skills/openclaw/caltwin/references/calibration.md
```

Content per spec §2. install_check.sh verifies twin-runtime installed + initialized.

### 验证

```bash
python3 -c "import yaml; yaml.safe_load(open('skills/openclaw/caltwin/SKILL.md').read().split('---')[1])"
bash skills/openclaw/caltwin/scripts/install_check.sh
```

Commit: `feat(D1): OpenClaw skill — SKILL.md + heartbeat + install check`

---

## Step 6: 集成测试 + Flywheel Effect 验证（1 天）

分两部分：6a 管道连通性，6b 效果验证。

### 6a. 管道连通性测试

`tests/test_implicit/test_integration.py`:

```python
@pytest.mark.requires_llm
def test_end_to_end_heartbeat():
    # 1. Bootstrap twin
    # 2. orchestrator run × 3 (option_set filled)
    # 3. Manual 1 outcome
    # 4. Mock git log matching 2 remaining traces
    # 5. HeartbeatReflector.run()
    # 6. assert auto_reflected + queued == 2
    # 7. assert experience library grew
    # 8. assert ExperienceUpdater used (not direct add)

def test_reflect_triggers_mining():
    # 1. Create 20 mock outcomes (5 failures)
    # 2. Set reflect_count file to 19
    # 3. cmd_reflect (20th)
    # 4. assert HardCaseMiner triggered
    # 5. assert PatternInsight in library
    # 6. assert reflect_count reset to 0
```

### 6b. Flywheel Effect Test

**新文件**: `scripts/verify_flywheel.py`

不进 CI，手动运行，~60-80 次 LLM 调用（Sonnet ~$0.3-0.5）。

**逻辑**: 同一批 10 个场景跑 3 轮，每轮之间 reflect outcomes，观察 CF 变化。

```
Round 0: bootstrap → run 10 scenarios → CF_0
Round 1: reflect 10 outcomes → run 同样 10 scenarios → CF_1
Round 2: reflect 10 outcomes → run 同样 10 scenarios → CF_2
```

10 个场景都有预设 ground truth（模拟用户真实偏好），脚本自动比对。

```python
# scripts/verify_flywheel.py
"""
Flywheel effect verification — manual run, not CI.
~60-80 LLM calls (Sonnet ~$0.3-0.5).

Usage: python scripts/verify_flywheel.py [--rounds 3] [--scenarios 10]
"""

SCENARIOS = [
    {"query": "用 Redis 还是 Memcached 做缓存？", "options": ["Redis", "Memcached"], "ground_truth": "Redis"},
    {"query": "新项目用 monorepo 还是 multirepo？", "options": ["monorepo", "multirepo"], "ground_truth": "monorepo"},
    {"query": "团队沟通用异步文档还是同步会议？", "options": ["异步文档", "同步会议"], "ground_truth": "异步文档"},
    {"query": "技术债要不要现在还？", "options": ["现在还", "先做需求"], "ground_truth": "现在还"},
    {"query": "新人 onboarding 让他直接上手还是先培训？", "options": ["直接上手", "先培训"], "ground_truth": "直接上手"},
    {"query": "要不要引入新框架替换现有的？", "options": ["引入新框架", "继续用现有的"], "ground_truth": "继续用现有的"},
    {"query": "CI 失败要不要 block merge？", "options": ["严格 block", "允许 override"], "ground_truth": "严格 block"},
    {"query": "API 版本策略用 URL path 还是 header？", "options": ["URL path", "header"], "ground_truth": "URL path"},
    {"query": "数据库选 PostgreSQL 还是 MySQL？", "options": ["PostgreSQL", "MySQL"], "ground_truth": "PostgreSQL"},
    {"query": "部署策略用蓝绿还是滚动？", "options": ["蓝绿部署", "滚动部署"], "ground_truth": "蓝绿部署"},
]

def run_round(twin, scenarios, round_idx):
    """Run all scenarios, return CF score."""
    correct = 0
    for s in scenarios:
        trace = orchestrator_run(query=s["query"], option_set=s["options"], twin=twin)
        # Check if top prediction matches ground truth
        ranking = _extract_ranking(trace)
        if ranking and ranking[0].lower().strip() == s["ground_truth"].lower().strip():
            correct += 1
    cf = correct / len(scenarios)
    print(f"  Round {round_idx}: CF = {cf:.0%} ({correct}/{len(scenarios)})")
    return cf

def reflect_round(twin, scenarios, trace_store, cal_store, exp_store, llm):
    """Reflect all outcomes from previous round."""
    for s in scenarios:
        # reflect with ground truth
        ...

def main():
    # Bootstrap → Round 0 → Reflect → Round 1 → Reflect → Round 2
    cf_scores = []
    for round_idx in range(n_rounds):
        cf = run_round(twin, scenarios, round_idx)
        cf_scores.append(cf)
        if round_idx < n_rounds - 1:
            reflect_round(...)

    # Verdict
    cf_0, cf_last = cf_scores[0], cf_scores[-1]
    if cf_last > cf_0:
        print(f"\n✓ PASS: Flywheel is turning. CF improved {cf_0:.0%} → {cf_last:.0%}")
    elif cf_last == cf_0:
        print(f"\n⚠ WARN: CF stagnant at {cf_0:.0%}. Check search/retrieval.")
    else:
        print(f"\n✗ FAIL: CF regressed {cf_0:.0%} → {cf_last:.0%}. Check ExperienceUpdater.")
```

**验收标准**:

| 指标 | Pass | Warn | Fail |
|------|------|------|------|
| CF_2 > CF_0 | 飞轮在转 | — | — |
| CF_2 == CF_0 | — | 停滞 | — |
| CF_2 < CF_0 | — | — | 反转 |

**诊断指南**（如果不 pass）:
- CF_0 就 >0.8 → 换更难场景集
- CF_1 == CF_0 → 检查 ExperienceLibrary.search 是否返回相关经验
- CF_2 < CF_1 → 检查 ExperienceUpdater 冲突检测
- 全程 <0.3 → bootstrap 答案与 ground truth 偏好不匹配

Commit: `test(D): integration tests + flywheel effect verification script`

---

## Step 7: 文档 + 最终验收（0.5 天）

### README

CLI 表新增:
```
twin-runtime heartbeat       Run implicit reflection from local signals
twin-runtime confirm         Confirm/reject pending implicit reflections
twin-runtime mine-patterns   Analyze systematic failure patterns
```

### 最终验收

```bash
pytest -q -m "not requires_llm"    # target 530+ passed
ruff check src/ tests/
twin-runtime heartbeat
twin-runtime confirm --list
twin-runtime mine-patterns --lookback 10
python scripts/verify_flywheel.py  # manual, ~$0.3-0.5 LLM cost
```

Commit: `docs: D phase — README + CHANGELOG`

---

## 执行顺序

```
Step 0: 前置改动 (5 项)                     ── 1 天
Step 1: ExperienceUpdater (D3)              ── 1 天
Step 2: HeartbeatReflector (D2)             ── 2 天
Step 3: CLI heartbeat+confirm               ── 1 天
Step 4: HardCaseMiner (D4)                  ── 1.5 天
Step 5: OpenClaw Skill (D1)                 ── 0.5 天
Step 6: 集成测试 + Flywheel Effect 验证     ── 1 天
Step 7: 文档 + 验收                         ── 0.5 天
                                            ──────────
                                             合计 8.5 天
```

D3 在 D2 前面：HeartbeatReflector._auto_reflect 依赖 ExperienceUpdater。
D1 在最后：静态文件，不影响其他组件，可根据 D2-D4 实际接口微调。
