# Spec: D — Implicit Reflection + OpenClaw Skill (v3 final)

> **Status**: Final (11 spec review + 8 plan review + 3 interface alignment + CLI split update)
> **前置依赖**: B（ExperienceLibrary + ReflectionGenerator + ConsistencyChecker）
> **产出**: OpenClaw skill、Heartbeat implicit reflection、ExperienceUpdater、Hard-case pattern mining
> **预估工期**: 8-10 天

---

## Review 修正总表（22 项）

### Spec Review（11 项）

| # | 级别 | 修正 |
|---|------|------|
| 1 | 高 | pending = trace-outcome 差集 + RuntimeDecisionTrace 加 option_set |
| 2 | 高 | reflect CLI 加 --source/--confidence + OutcomeSource 扩展 |
| 3 | 高 | ExperienceUpdater 用 search_entries() 返回可变 entry |
| 4 | 高 | HeartbeatReflector 接受 store 参数不自己拼路径 |
| 5 | 高 | HardCaseMiner 通过 LLMPort.ask_json() |
| 6 | 中 | Heartbeat 内部调 Python API，仅 OpenClaw shell hook 用 CLI |
| 7 | 中 | pending queue atomic write (tmpfile + rename) |
| 8 | 中 | InferredReflection/HeartbeatReport 改为 Pydantic BaseModel |
| 9 | 中 | HardCaseMiner 独立实现分组（输入类型不同，强行复用是过度抽象） |
| 10 | 低 | SKILL.md metadata 保持内联 JSON + 注释说明 |
| 11 | 低 | extract_keywords 提升为 domain/utils/text.py 公共 util |

### Plan Review（8 项）

| # | 级别 | 修正 |
|---|------|------|
| P1 | 高 | record_outcome 不传 confidence（语义不同：推断置信度 ≠ outcome 置信度） |
| P2 | 中 | HardCaseMiner 自己写分组（3-5 行 defaultdict），不复用 bias_detector |
| P3 | 中 | ExperienceLibrary 加 add_pattern(PatternInsight) 方法 |
| P4 | 低 | 无 count() → 改为 len(list_outcomes()) |
| P5 | 中 | list_traces() 返回 ID → _find_pending 逐个 load_trace + limit=200 |
| P6 | 低 | domain/utils/ 不存在 → Step 0 中创建目录 + __init__.py |
| P7 | 低 | Step 0e search_entries() → 已在 B 中完成，删除 |
| P8 | 中 | outcome_count % 20 → 改为文件计数器 reflect_count |

### Interface Alignment（3 项）

| # | 级别 | 修正 |
|---|------|------|
| I1 | 高 | _auto_reflect 调 record_outcome 签名错误 → 需传 twin, trace_store, calibration_store（非 store=） |
| I2 | 中 | CalendarAdapter/GmailAdapter 无 fetch_recent() → 改用 scan(since=now-24h) |
| I3 | 低 | add_pattern 用 self.patterns（非 self._patterns，Pydantic 字段名） |

---

## 1. 前置改动（D 实现前必须先做）

### 1.1 RuntimeDecisionTrace 加 option_set

```python
# domain/models/runtime.py
class RuntimeDecisionTrace(BaseModel):
    ...
    option_set: List[str] = Field(default_factory=list)
```

orchestrator run() 中赋值：`trace.option_set = option_set`（在返回 trace 之前）。

### 1.2 OutcomeSource 扩展

```python
# domain/models/primitives.py
class OutcomeSource(str, Enum):
    USER_CORRECTION = "user_correction"
    USER_REFLECTION = "user_reflection"
    OBSERVED = "observed"
    IMPLICIT_GIT = "implicit_git"
    IMPLICIT_FILE = "implicit_file"
    IMPLICIT_CALENDAR = "implicit_calendar"
    IMPLICIT_EMAIL = "implicit_email"
```

### 1.3 reflect CLI 加 --source / --confidence

**文件**: `cli/_main.py` (argparse) + `cli/_calibration.py` (cmd_reflect 实现)

```python
p_reflect.add_argument("--source", default="user_correction",
    choices=[s.value for s in OutcomeSource])
p_reflect.add_argument("--confidence", type=float, default=0.8)
```

`cmd_reflect` 中将 source 转为 OutcomeSource 枚举传入 record_outcome。**P1: confidence 不传入 record_outcome**，仅在 CLI 输出中展示。

### 1.4 extract_keywords 提升为公共 util

```python
# domain/utils/text.py（P6: 需先创建 domain/utils/__init__.py）
def extract_keywords(text: str, max_keywords: int = 20) -> List[str]:
    """中英文关键词提取，CJK bigram + 停用词过滤。"""
```

4 个消费方切换：memory_access_planner / ReflectionGenerator / ConsistencyChecker / HeartbeatReflector。

### 1.5 ExperienceLibrary 加 add_pattern()

```python
# domain/models/experience.py
def add_pattern(self, pattern: PatternInsight) -> None:
    # I3: Pydantic 字段名是 self.patterns（非 self._patterns）
    self.patterns.append(pattern)
```

P7: search_entries() 已在 B 中完成，不需要再加。

---

## 2. D1: OpenClaw Skill

### 2.1 目录结构

```
skills/openclaw/caltwin/
├── SKILL.md
├── scripts/
│   ├── heartbeat_reflect.py
│   └── install_check.sh
└── references/
    └── calibration.md
```

### 2.2 SKILL.md

```yaml
---
name: caltwin
description: >
  Calibrated judgment twin for work decisions. Provides personalized
  recommendations calibrated to the user's actual decision-making patterns.
license: Apache-2.0
# NOTE: metadata must be single-line JSON — OpenClaw parser requirement (#10)
metadata: {"openclaw":{"requires":{"bins":["twin-runtime"],"env":["ANTHROPIC_API_KEY"]},"install":[{"id":"pip","kind":"pip","package":"twin-runtime","bins":["twin-runtime"]}]}}
homepage: https://github.com/ZiyaZhang/caltwin
---

# CalTwin — Calibrated judgment twin

## When to invoke
- User faces a work decision with 2+ options and trade-offs
- User asks "what would I choose", "what should I do"

## Decision flow
1. Extract question and 2-4 options from context
2. Run: `twin-runtime run "<question>" -o "<opt1>" "<opt2>" --json`
3. Present with honest uncertainty
4. If confidence < 0.5: say "I don't have enough data"

## Recording outcomes
`twin-runtime reflect --trace-id <id> --choice "<actual>"`

## Boundaries
- REFUSE on personal/medical/legal/financial domains
- DEGRADE on unfamiliar sub-domains
- Present as prediction, never prescription
```

---

## 3. D2: Heartbeat Implicit Reflection

### 3.1 核心设计

- **Pending = trace-outcome 差集**（#1）
- **Options 从 trace.option_set 读取**（#1）
- **内部调 Python API**（#6）：record_outcome() + ReflectionGenerator
- **I1: record_outcome 需传 twin, trace_store, calibration_store**（非简化的 store=）
- **P1: confidence 不传入 record_outcome**
- **I2: Calendar/Email 用 adapter.scan(since=now-24h)**（非 fetch_recent）
- **接受 store 参数**（#4）
- **Pydantic BaseModel**（#8）
- **复用 extract_keywords()**（#11）
- **Atomic write**（#7）

### 3.2 信号源

| 信号源 | 适配器 | 调用方式 | 置信度 |
|--------|--------|---------|--------|
| git_prs | subprocess | `git log --merges --since=24h` | 0.5-0.9 |
| git_commits | subprocess | `git log --since=24h --no-merges` | 0.3-0.85 |
| calendar | CalendarAdapter | `adapter.scan(since=now-24h)` (I2) | 0.4-0.7 |
| email | GmailAdapter | `adapter.scan(since=now-24h)` (I2) | 0.3-0.6 |
| file_changes | subprocess | `find . -mtime -1` | 0.2-0.5 |

Calendar/Email 未配置时静默跳过。

### 3.3 _auto_reflect 调用签名（I1 修正）

```python
def _auto_reflect(self, inf: InferredReflection):
    trace = self._trace_store.load_trace(inf.trace_id)
    twin = self._twin_store.load_state(self._user_id)
    exp_lib = self._experience_store.load()

    # I1: 完整签名，非简化的 store=
    outcome, update = record_outcome(
        trace_id=inf.trace_id,
        actual_choice=inf.inferred_choice,
        source=inf.signal_source,
        twin=twin,
        trace_store=self._trace_store,
        calibration_store=self._calibration_store,
    )

    reflection = ReflectionGenerator(self._llm).process(
        trace, inf.inferred_choice, exp_lib)
    if reflection.new_entry:
        ExperienceUpdater().update(reflection.new_entry, exp_lib)
    self._experience_store.save(exp_lib)
```

### 3.4 Calendar/Email 推断（I2 修正）

```python
def _infer_from_calendar(self, pending) -> List[InferredReflection]:
    if not self._calendar_adapter:
        return []
    # I2: 用 scan(since=) 而非 fetch_recent()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    fragments = self._calendar_adapter.scan(since=since)
    event_text = " ".join(f.summary.lower() for f in fragments if f.summary)
    # keyword match pending traces...

def _infer_from_email(self, pending) -> List[InferredReflection]:
    if not self._gmail_adapter:
        return []
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    fragments = self._gmail_adapter.scan(since=since)
    # filter to sent only if possible, keyword match...
```

### 3.5 CLI

**新文件**: `cli/_implicit.py` (heartbeat + confirm + mine-patterns 命令实现)
**改动**: `cli/_main.py` (argparse + commands dict)

```
twin-runtime heartbeat              # 构造 HeartbeatReflector → run()
twin-runtime confirm                # 交互式确认
twin-runtime confirm --list
twin-runtime confirm --accept-all
```

---

## 4. D3: ExperienceUpdater

```python
# application/calibration/experience_updater.py

class ExperienceUpdater:
    def update(self, new_entry, library) -> UpdateResult:
        similar = library.search_entries(new_entry.scenario_type, top_k=3)  # #3
        # → ADDED / CONFIRMED / SUPERSEDED / REJECTED
```

替换 B 的直接 `exp_lib.add()`。

---

## 5. D4: Hard-case Pattern Mining

```python
# application/calibration/hard_case_miner.py

class HardCaseMiner:
    def __init__(self, llm: LLMPort, min_failures=3):  # #5
        ...
    def mine(self, traces, outcomes) -> List[PatternInsight]:
        # P2: 独立分组
        groups = defaultdict(list)
        for f in failures:
            groups[f_domain].append(f)
        # #5: self._llm.ask_json()
        # → PatternInsight (weight=2.0)
```

### 触发（P8: 文件计数器）

```python
# cmd_reflect 中
count = _increment_reflect_counter(user_id)
if count >= 20:
    patterns = HardCaseMiner(llm).mine(traces, outcomes)
    for p in patterns:
        exp_lib.add_pattern(p)  # P3, I3: self.patterns.append()
    _reset_reflect_counter(user_id)
```

CLI: `twin-runtime mine-patterns [--min-failures N] [--lookback N]`

---

## 6. 验收 Checklist

- [ ] RuntimeDecisionTrace.option_set + orchestrator 赋值
- [ ] OutcomeSource 扩展 4 个 implicit 变体
- [ ] reflect CLI --source / --confidence（confidence 不传入 record_outcome）
- [ ] domain/utils/text.py + 4 消费方切换
- [ ] ExperienceLibrary.add_pattern() 用 self.patterns（非 _patterns）
- [ ] SKILL.md 符合 AgentSkills spec
- [ ] heartbeat: trace-outcome 差集 + 逐个 load_trace(limit=200)
- [ ] heartbeat: _auto_reflect 用完整 record_outcome 签名 (twin, trace_store, calibration_store)
- [ ] heartbeat: Calendar/Email 用 adapter.scan(since=) 非 fetch_recent()
- [ ] heartbeat: Calendar/Email 未配置静默跳过
- [ ] heartbeat: 高置信度调 Python API（不传 confidence）
- [ ] heartbeat: 低置信度 atomic write
- [ ] confirm 命令
- [ ] ExperienceUpdater 替代直接 add()
- [ ] HardCaseMiner 通过 LLMPort.ask_json()
- [ ] HardCaseMiner 独立分组
- [ ] 文件计数器 + 每 20 次触发 mining
- [ ] Offline + Online tests 通过
- [ ] scripts/verify_flywheel.py: CF_2 > CF_0（flywheel effect verified）
- [ ] README + CHANGELOG 更新
