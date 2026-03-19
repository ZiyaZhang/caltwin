# Plan: E — Post-Demo Infrastructure

> **Spec version**: v5 (50-54 corrections)
> **Estimated effort**: 9-11 days
> **Prerequisites**: C (Shadow Mode Demo) ✅ + 融资完成
> **Execution**: E1‖E2‖E3‖E5 并行 → E4（仅在 prototype 有效时）

### Plan review 修正记录

**Round 1（7 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| E-P1 | 高 | DSPy adapter 的 TrainingExample → Module 输入转换未定义 | 新增 Step 1.5b，从 trace 重建 stage 输入上下文 |
| E-P2 | 高 | Pipeline prompt 注入改 3 个文件有架构风险 | 改为 client 层注入：prompt prefix registry |
| E-P3 | 中 | Mem0 _sync_to_mem0 缺少去重 | sync 前 get_all 取已有 entry_id，只同步 diff |
| E-P4 | 中 | 行为推断引用 t.stakes 但 trace 无直接 stakes 字段 | 从 trace.situation_frame dict 提取 |
| E-P5 | 中 | E1/E2 并行时 E1 依赖 JSON backend | 标注开发期用 JSON，Day 5 回归测试 SQLite |
| E-P6 | 低 | Mem0 → ExperienceEntry 重建缺必填字段 | 补充 applicable_when + created_at 默认值 |
| E-P7 | 低 | E4 时间线 Day 5-6 与 E1 冲突 | 修正为 Day 6-7 |

**Round 2（9 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| E-P8 | 高 | Step 1.7 用 system prompt 子串匹配识别 stage 太脆弱 | 改为 ask_json/ask_structured 加显式 `stage` 参数（Optional[str]=None） |
| E-P9 | 中 | build_training_set "跳过不可靠 outcome_source" 未定义什么是不可靠 | 明确：所有 outcome_source 都保留，只跳过 trace 加载失败的记录 |
| E-P10 | 中 | E2 SqliteTraceStore.list_traces 的 SQL schema 无 user_id 列 | traces 表加 user_id 列 + index，对齐 Port 签名 |
| E-P11 | 中 | E1 4 天可能偏乐观，Step 1.5b trace → stage 输入重建是难点 | 标注 1.5b 为关键路径，预留 0.5 天 buffer（从 1.9 holdout 借） |
| E-P12 | 中 | E3 load() local-first 导致跨设备新增数据永远不可见 | 改为 load 时尝试 merge：local + Mem0 diff 合并 |
| E-P13 | 中 | E5 _is_aggressive_choice 未定义 | 给出定义：选项在 option_ranking 中排名靠后 + stakes=high 时仍选择 |
| E-P14 | 低 | E4 prototype 成本 "$1-5" 和生产 "$100-120" 估算方式不一致 | 统一用 token 估算 |
| E-P15 | 低 | E3 Letta 0.5 天可能浪费，API 不稳定就 stub | 改为 Letta deferred，0.5 天用于 Mem0 健壮性（重试、分页） |
| E-P16 | 低 | E1 holdout "baseline CF" 未定义 | 明确：优化前在 holdout 上跑一次的 CF |

---

## 执行概览

```
         E1 (DSPy)     E2 (SQLite)    E3 (Mem0)      E5 (Curator)
         [4d]          [2d]           [2d]            [2d]
         ─────────     ──────         ──────          ──────
Day 1    1.1-1.3       2.1-2.2
Day 2    1.4-1.5       2.3-2.5
Day 3    1.6-1.7                      3.1-3.3         5.1-5.2
Day 4    1.8                          3.4-3.5         5.3-5.5
Day 5    1.9 (holdout)                                回归测试
                                          ↓
                                    E4 (EvoAgentX) [2d prototype]
Day 6-7                               4.1-4.5 (仅在 E1 完成 + prototype Go 时)
```

**说明**：4 条并行轨道由 1-2 人执行时，实际日历时间取决于团队规模。单人串行 ≈ 10 天，双人并行 ≈ 5-6 天。

**E-P5 注意**：E1 在 Day 1-5 开发期使用 JSON backend。E2 在 Day 2 完成后，Day 5 的回归测试验证 E1 在 SQLite backend 下也能工作。

---

## E1: DSPy Prompt Optimization (4 天)

### 目标

用 DSPy 自动优化 pipeline 3 个 LLM stage 的 prompt，提升 CF ≥ 3pp。

### Step 1.1: DSPy 环境 + 依赖 (0.25 天)

**安装**：
```bash
pip install dspy-ai
```

**验证**：DSPy 版本兼容 Anthropic backend。配置 `dspy.settings.configure(lm=dspy.Anthropic(model="claude-sonnet-4-20250514"))`。

### Step 1.2: TrainingExample model (0.25 天)

**文件**: `src/twin_runtime/application/optimization/prompt_optimizer.py`（新建）

```python
class TrainingExample(BaseModel):
    query: str
    option_set: List[str]
    ground_truth_choice: str
    domain: DomainEnum
    stakes: OrdinalTriLevel
    trace_id: str
    # 以下字段用于重建 stage 输入上下文（修正 E-P1）
    situation_frame_json: Optional[str] = None    # 原始 trace 中的 situation_frame
    head_assessments_json: Optional[str] = None   # 原始 trace 中的 head_assessments
    twin_state_version: Optional[str] = None
```

### Step 1.3: build_training_set (0.5 天)

**文件**: 同上

```python
def build_training_set(
    outcome_store, trace_store, min_examples: int = 20
) -> List[TrainingExample]:
```

**逻辑**（spec #40，修正 E-P9）：
1. `outcome_store.list_outcomes(limit=500)` → 全部 outcomes
2. 对每个 outcome，try `trace_store.load_trace(outcome.trace_id)` → trace
3. 构造 TrainingExample（含 trace 中的 situation_frame 和 head_assessments 用于 stage 输入重建）
4. **保留所有 outcome**（HIT + MISS + PARTIAL），不跳过 rank>1
5. **保留所有 outcome_source**（修正 E-P9：含 implicit_git/file/calendar/email，这些是数据量最大的来源）
6. 只跳过 **trace 加载失败**的记录（FileNotFoundError → log warning, continue）
7. 如果结果 < min_examples，raise InsufficientDataError

**测试**：
- `test_build_training_set_includes_all_outcomes` — HIT + MISS + PARTIAL 全保留
- `test_build_training_set_min_examples` — <20 时 raise error

### Step 1.4: cf_metric 函数 (0.25 天)

```python
def cf_metric(example: TrainingExample, prediction: Dict) -> float:
    ranking = prediction.get("option_ranking", [])
    if not ranking:
        return 0.0
    score, rank = choice_similarity(ranking, example.ground_truth_choice)
    return {1: 1.0, 2: 0.5}.get(rank, 0.0)
```

复用 `fidelity_evaluator.choice_similarity`（spec #38）。

**测试**：
- `test_cf_metric_rank1` → 1.0
- `test_cf_metric_rank2` → 0.5
- `test_cf_metric_no_match` → 0.0
- `test_cf_metric_empty_ranking` → 0.0

### Step 1.5: DSPy Adapter Layer (1.0 天)

**文件**: `src/twin_runtime/application/optimization/dspy_adapters.py`（新建）

这是 spec #50 的核心修正。现有 pipeline 直接调用 `LLMPort.ask_json()`，不是 DSPy Module。需要为每个 stage 编写 adapter。

**3 个 Signature + 3 个 Module**：

```python
# --- Situation Interpreter ---
class SituationInterpreterSignature(dspy.Signature):
    """Interpret a user query into a structured situation frame."""
    query: str = dspy.InputField()
    domain_context: str = dspy.InputField()
    twin_profile: str = dspy.InputField()
    situation_frame: str = dspy.OutputField(
        desc="JSON: {scenario_type, stakes, reversibility, time_pressure, domain}"
    )

class SituationInterpreterModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.interpret = dspy.Predict(SituationInterpreterSignature)

    def forward(self, query, domain_context, twin_profile):
        return self.interpret(
            query=query, domain_context=domain_context, twin_profile=twin_profile,
        )

# --- Head Activation ---
class HeadActivationSignature(dspy.Signature):
    """Activate a domain head to produce a judgment."""
    query: str = dspy.InputField()
    situation_frame: str = dspy.InputField()
    head_config: str = dspy.InputField()
    experience_context: str = dspy.InputField()
    judgment: str = dspy.OutputField(
        desc="JSON: {recommendation, confidence, reasoning, option_ranking}"
    )

class HeadActivationModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.activate = dspy.Predict(HeadActivationSignature)

    def forward(self, query, situation_frame, head_config, experience_context):
        return self.activate(
            query=query, situation_frame=situation_frame,
            head_config=head_config, experience_context=experience_context,
        )

# --- Decision Synthesizer ---
class DecisionSynthesizerSignature(dspy.Signature):
    """Synthesize multiple head judgments into a final decision."""
    query: str = dspy.InputField()
    head_judgments: str = dspy.InputField()
    arbiter_result: str = dspy.InputField()
    twin_profile: str = dspy.InputField()
    final_decision: str = dspy.OutputField(
        desc="JSON: {decision, confidence, reasoning, option_ranking}"
    )

class DecisionSynthesizerModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.synthesize = dspy.Predict(DecisionSynthesizerSignature)

    def forward(self, query, head_judgments, arbiter_result, twin_profile):
        return self.synthesize(
            query=query, head_judgments=head_judgments,
            arbiter_result=arbiter_result, twin_profile=twin_profile,
        )
```

### Step 1.5b: TrainingExample → DSPy Example 转换（修正 E-P1）

**关键问题**：DSPy Module 的 forward() 需要具体的 stage 输入（domain_context, twin_profile, head_config 等），但 TrainingExample 只有 query + ground_truth。需要从 trace 中重建这些输入。

```python
def _to_dspy_examples(
    training_set: List[TrainingExample], stage: str
) -> List[dspy.Example]:
    """从 TrainingExample 重建 stage-specific DSPy Examples。

    每个 trace 中记录了 pipeline 执行时的完整上下文：
    - situation_frame: SituationFrame 的 JSON dump
    - head_assessments: HeadAssessment 列表的 JSON dump
    这些是 pipeline 实际输入的快照，可直接用于 DSPy 训练。
    """
    examples = []
    for te in training_set:
        if stage == "situation_interpreter":
            # 输入：query + domain keywords（从 trace.activated_domains 提取）
            # 输出：situation_frame JSON
            if not te.situation_frame_json:
                continue
            ex = dspy.Example(
                query=te.query,
                domain_context=json.dumps([d.value for d in te.domain]),
                twin_profile="",  # 简化：SI 不依赖完整 profile
                situation_frame=te.situation_frame_json,
            ).with_inputs("query", "domain_context", "twin_profile")

        elif stage == "head_activation":
            # 输入：query + situation_frame + head config
            # 输出：judgment JSON（ground truth = actual_choice 排第一）
            if not te.situation_frame_json:
                continue
            gt_ranking = [te.ground_truth_choice] + [
                o for o in te.option_set if o != te.ground_truth_choice
            ]
            ex = dspy.Example(
                query=te.query,
                situation_frame=te.situation_frame_json,
                head_config="{}",  # 简化
                experience_context="",
                judgment=json.dumps({"option_ranking": gt_ranking, "confidence": 0.8}),
            ).with_inputs("query", "situation_frame", "head_config", "experience_context")

        elif stage == "decision_synthesizer":
            # 输入：query + head_judgments + arbiter
            # 输出：final_decision JSON
            if not te.head_assessments_json:
                continue
            ex = dspy.Example(
                query=te.query,
                head_judgments=te.head_assessments_json,
                arbiter_result="{}",
                twin_profile="",
                final_decision=json.dumps({
                    "decision": te.ground_truth_choice,
                    "option_ranking": [te.ground_truth_choice],
                    "confidence": 0.8,
                }),
            ).with_inputs("query", "head_judgments", "arbiter_result", "twin_profile")
        else:
            continue
        examples.append(ex)
    return examples
```

**测试**：
- `test_to_dspy_examples_si` — situation_interpreter stage 转换正确
- `test_to_dspy_examples_ha` — head_activation stage，ground_truth 排第一
- `test_to_dspy_examples_skips_missing_data` — situation_frame 缺失时跳过
- `test_adapter_output_parseable` — 输出可 JSON parse

### Step 1.6: PromptOptimizer.optimize (0.75 天)

```python
class PromptOptimizer:
    def __init__(self, framework: str = "dspy"):
        self._framework = framework

    def optimize(
        self,
        stage: str,
        training_set: List[TrainingExample],
        metric: Callable = cf_metric,
        num_trials: int = 50,
    ) -> OptimizedPrompt:
        module = self._get_module(stage)
        dspy_examples = _to_dspy_examples(training_set, stage)

        teleprompter = BootstrapFewShot(
            metric=self._wrap_metric(metric),
            max_bootstrapped_demos=3,
            max_labeled_demos=5,
        )

        optimized = teleprompter.compile(module, trainset=dspy_examples)
        return self._extract_prompt(optimized, stage)
```

**OptimizedPrompt model**：

```python
class OptimizedPrompt(BaseModel):
    stage: str
    system_prefix: str
    few_shot_examples: List[Dict]
    optimized_at: datetime
    training_size: int
    metric_score: float
```

### Step 1.7: Prompt 存储 + Pipeline 注入（修正 E-P2）

**存储位置**: `~/.twin-runtime/store/<user_id>/prompts/<stage>.json`

**Pipeline 注入方式（修正 E-P2 + E-P8：client 层注入，显式 stage 参数）**：

在 `infrastructure/llm/client.py` 中添加 prompt prefix registry + 显式 stage 参数：

```python
# client.py 新增

_prompt_prefixes: Dict[str, str] = {}

def load_optimized_prompts(store_dir: Path, user_id: str) -> None:
    """Pipeline 启动时加载所有已优化的 prompt prefix。"""
    prompts_dir = store_dir / user_id / "prompts"
    if not prompts_dir.exists():
        return
    for stage_file in prompts_dir.glob("*.json"):
        opt = OptimizedPrompt.model_validate_json(stage_file.read_text())
        prefix_parts = [opt.system_prefix]
        for ex in opt.few_shot_examples:
            prefix_parts.append(f"Example: {json.dumps(ex)}")
        _prompt_prefixes[opt.stage] = "\n\n".join(prefix_parts)
```

**修正 E-P8**：不用 system prompt 子串匹配（太脆弱）。改为给 `ask_json()` 和 `ask_structured()` 加可选 `stage` 参数：

```python
def ask_json(
    system: str, user: str, model: str | None = None,
    max_tokens: int = 2048, *, temperature: float | None = None,
    stage: str | None = None,  # 新增：显式 stage 标识
) -> Dict[str, Any]:
    # 如果有 stage 且该 stage 有优化 prefix，拼接
    if stage and stage in _prompt_prefixes:
        system = _prompt_prefixes[stage] + "\n\n" + system
    ...
```

Pipeline 调用方（3 处）加 stage 参数，改动量极小：

```python
# situation_interpreter.py
llm.ask_structured(..., stage="situation_interpreter")

# head_activator.py
llm.ask_structured(..., stage="head_activation")

# decision_synthesizer.py
llm.ask_json(..., stage="decision_synthesizer")
```

**优势**：显式、不依赖 prompt 文本内容、向后兼容（stage=None 时无注入）。

**Pipeline 启动接线**：在 `runtime_orchestrator.run()` 入口处调用 `load_optimized_prompts()`（lazy，首次调用时加载）。

**测试**：
- `test_prefix_applied_with_stage` — stage="situation_interpreter" → prefix 拼接
- `test_no_prefix_without_stage` — stage=None → 原始 prompt
- `test_no_prefix_when_empty` — 未优化 → 原始 prompt 不变
- `test_load_optimized_prompts` — 从文件加载 → registry 正确填充

### Step 1.8: CLI optimize 命令 (0.25 天)

```
twin-runtime optimize --stage situation_interpreter [--trials 50] [--min-training-examples 20]
twin-runtime optimize --all  # 依次优化 3 个 stage
```

### Step 1.9: Holdout 验证 (0.5 天，修正 E-P11：如 1.5b 超时可压缩)

从 training set 中 random split 80/20（train/holdout）。

**Baseline CF（修正 E-P16）**：在 holdout 上用**未优化的原始 prompt** 跑一次，得到 baseline_cf。这是优化前的性能基线。

**验收标准**：
- holdout CF ≥ train CF - 2pp（无严重过拟合）
- holdout CF ≥ baseline_cf + 3pp（优化有效）
- 如果不达标但 ≥ baseline_cf + 1pp：接受但标注为 "marginal improvement"

**E-P11 buffer 注意**：Step 1.5b（trace → stage 输入重建）是关键路径难点。如果 1.5b 消耗超过 1 天，从 1.9 借 0.25 天（简化 holdout 为一次快速验证而非完整 benchmark）。

### 交付物

- [x] `TrainingExample` + `OptimizedPrompt` models
- [x] `build_training_set()` — 保留 HIT+MISS+PARTIAL，含 trace context 字段
- [x] `cf_metric()` — 复用 choice_similarity
- [x] 3 个 DSPy Signature + Module adapters
- [x] `_to_dspy_examples()` — TrainingExample → stage-specific DSPy Example 转换
- [x] `PromptOptimizer.optimize()`
- [x] Client 层 prompt prefix registry（pipeline 零改动）
- [x] CLI `twin-runtime optimize`
- [x] ~16 个 tests

---

## E2: SQLite Append-Only Persistence (2 天)

### 目标

为 OutcomeStore 和 TraceStore 提供 SQLite backend，解决 JSON 的 >500 条性能瓶颈。

### Step 2.1: Schema 设计 (0.25 天)

```sql
CREATE TABLE outcomes (
    outcome_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    actual_choice TEXT NOT NULL,
    outcome_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX idx_outcomes_trace_id ON outcomes(trace_id);
CREATE INDEX idx_outcomes_created_at ON outcomes(created_at);
CREATE INDEX idx_outcomes_user_id ON outcomes(user_id);

-- 修正 E-P10: traces 表加 user_id 列，对齐 Port 签名 list_traces(user_id, limit)
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL,
    final_decision TEXT NOT NULL,
    decision_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX idx_traces_created_at ON traces(created_at);
CREATE INDEX idx_traces_user_id ON traces(user_id);
```

**注意**：当前是单用户场景，user_id 默认空字符串与 JSON 实现行为一致。多用户场景时 user_id 列生效。

### Step 2.2: SqliteOutcomeStore (0.5 天)

**文件**: `src/twin_runtime/infrastructure/backends/sqlite/outcome_store.py`

实现 `OutcomeStore` Protocol。

### Step 2.3: SqliteTraceStore (0.5 天)

**文件**: `src/twin_runtime/infrastructure/backends/sqlite/trace_store.py`

实现 `TraceStore` Protocol。

### Step 2.4: 迁移命令 (0.5 天)

**文件**: `src/twin_runtime/cli/_migration.py`（新建）

```
twin-runtime migrate --to sqlite    # JSON → SQLite
twin-runtime migrate --to json      # SQLite → JSON (全量导出)
```

### Step 2.5: 性能测试 + 后端路由 (0.25 天)

```python
# infrastructure/store_factory.py
def create_outcome_store(config) -> OutcomeStore:
    if config.storage_backend == "sqlite":
        return SqliteOutcomeStore(db_path=...)
    return JsonCalibrationStore(...)  # 现有 JSON 实现
```

### 交付物

- [x] `SqliteOutcomeStore` + `SqliteTraceStore`
- [x] `twin-runtime migrate --to sqlite/json`
- [x] `store_factory.py`
- [x] ~10 个 tests（含 benchmark）

---

## E3: Mem0 / Letta ExperienceLibrary Adapters (2 天)

### 目标

抽取 ExperienceLibraryStore Protocol + 实现 Mem0 跨设备同步。

### Step 3.1: ExperienceLibraryStorePort Protocol (0.5 天)

**文件**: `src/twin_runtime/domain/ports/experience_store.py`（新建）

```python
@runtime_checkable
class ExperienceLibraryStorePort(Protocol):
    def load(self) -> ExperienceLibrary: ...
    def save(self, library: ExperienceLibrary) -> None: ...
```

### Step 3.2: Mem0ExperienceStore (0.75 天)

**文件**: `src/twin_runtime/infrastructure/backends/mem0/experience_store.py`（新建）

```python
class Mem0ExperienceStore:
    def __init__(self, mem0_api_key: str, user_id: str, store_dir: str):
        from mem0 import MemoryClient
        self._client = MemoryClient(api_key=mem0_api_key)
        self._user_id = user_id
        # 修正 E-P6: 正确类名和签名
        from twin_runtime.infrastructure.backends.json_file.experience_store import (
            ExperienceLibraryStore,
        )
        self._local = ExperienceLibraryStore(store_dir, user_id)

    def save(self, library: ExperienceLibrary) -> None:
        self._local.save(library)
        self._sync_to_mem0(library)

    def load(self) -> ExperienceLibrary:
        """修正 E-P12: merge 策略而非 local-only。

        1. 始终加载本地（最新 write-through 数据）
        2. 尝试从 Mem0 拉取 diff（其他设备新增的 entries）
        3. 合并 diff 到本地并保存
        4. Mem0 不可用时 fallback 到纯本地
        """
        local_lib = self._local.load()
        try:
            remote_lib = self._load_from_mem0()
            local_ids = {e.id for e in local_lib.entries}
            new_entries = [e for e in remote_lib.entries if e.id not in local_ids]
            if new_entries:
                for e in new_entries:
                    local_lib.add(e)
                self._local.save(local_lib)  # persist merged result
        except Exception:
            pass  # Mem0 不可用，用纯本地
        return local_lib

    def _sync_to_mem0(self, library: ExperienceLibrary):
        """增量同步（修正 E-P3：先查已有 entry_id，只同步 diff）。"""
        try:
            existing = self._client.get_all(user_id=self._user_id)
            existing_ids = {
                m.get("metadata", {}).get("entry_id")
                for m in existing
            }
            for entry in library.entries:
                if entry.id in existing_ids:
                    continue  # 已存在，跳过
                self._client.add(
                    messages=[{"role": "user", "content": entry.insight}],
                    user_id=self._user_id,
                    metadata={
                        "entry_id": entry.id,
                        "scenario_type": ",".join(entry.scenario_type),
                    },
                )
        except Exception as e:
            logger.warning("Mem0 sync failed (non-fatal): %s", e)

    def _load_from_mem0(self) -> ExperienceLibrary:
        """从 Mem0 全量拉取并构造 ExperienceLibrary。"""
        memories = self._client.get_all(user_id=self._user_id)
        entries = []
        for mem in memories:
            metadata = mem.get("metadata", {})
            # 修正 E-P6: 补充缺失的必填字段
            entries.append(ExperienceEntry(
                id=metadata.get("entry_id", str(uuid4())),
                insight=mem["memory"],
                scenario_type=metadata.get("scenario_type", "").split(","),
                applicable_when="Restored from Mem0 backup",  # 必填字段默认值
                entry_kind="narrative",
                weight=0.8,
                created_at=datetime.fromisoformat(
                    mem.get("created_at", datetime.now(timezone.utc).isoformat())
                ),
            ))
        return ExperienceLibrary(entries=entries, patterns=[])
```

**测试**（mock Mem0 client）：
- `test_save_writes_local_and_remote`
- `test_load_local_first`
- `test_load_fallback_to_mem0`
- `test_load_mem0_failure_fallback`
- `test_sync_skips_existing_entries` — 已有 entry_id 不重复同步
- `test_sync_failure_nonfatal`

### Step 3.3: Mem0 健壮性 + Letta deferred (0.5 天，修正 E-P15)

**Letta deferred**：Letta API 不稳定，0.5 天用于 Mem0 健壮性而非 Letta stub：
- `_sync_to_mem0` 添加重试逻辑（max 2 retries, exponential backoff）
- `get_all` 添加分页支持（Mem0 大量 entries 时 get_all 可能超时）
- 错误分类：网络错误 → 重试，认证错误 → 立即停止 + 提示用户检查 API key

Letta 集成在 E3 v2 中实现（post-user-study），不阻塞 E3 v1。

### Step 3.4: Config + 后端路由 (0.25 天)

在 `store_factory.py` 中扩展 experience store 路由。

### Step 3.5: 文档 (0.25 天)

明确 E3 v1 = 跨设备同步，语义检索 deferred 到 E3 v2。

### 交付物

- [x] `ExperienceLibraryStorePort` Protocol
- [x] `Mem0ExperienceStore` — merge-on-load, write-through, diff sync, retry
- [x] Letta deferred（E3 v2）
- [x] Config + 后端路由
- [x] E3 v1 定位文档
- [x] CHANGELOG entry
- [x] ~8 个 tests

---

## E4: EvoAgentX Workflow Evolution (2 天 prototype)

### 前置条件

- E1 完成（优化后 prompt 作为进化种子）
- Prototype 有效后才追加生产集成（+3 天）

### Step 4.1: EvoAgentX 调研 (0.5 天)

### Step 4.2: Pipeline → Workflow Graph 表示 (0.5 天)

### Step 4.3: Fitness function (0.25 天)

```python
def pipeline_fitness(workflow_config, holdout_scenarios) -> float:
    cf_scores = []
    for scenario in holdout_scenarios:
        trace = run_pipeline_with_config(workflow_config, scenario)
        score, rank = choice_similarity([trace.final_decision], scenario.ground_truth)
        cf_scores.append(1.0 if rank == 1 else 0.0)
    return sum(cf_scores) / len(cf_scores)
```

### Step 4.4: Minimal evolution run (0.5 天)

5 individuals × 3 generations × 5 scenarios = 75 pipeline runs × ~5 API calls = ~375 API calls

**成本（修正 E-P14：统一 token 估算）**：375 calls × ~1K input + 500 output tokens = ~375K input ($1.1) + ~188K output ($2.8) ≈ **~$4**

### Step 4.5: Prototype 报告 (0.25 天)

Go/No-Go 标准：CF 提升 > 2pp 且 p < 0.1

**生产成本（修正 E-P14）**：2000 pipeline runs × ~5 = ~10000 API calls × (~1K input + 500 output) = 10M input ($30) + 5M output ($75) ≈ **~$105**。

### 交付物

- [x] 调研报告 + Go/No-Go 决策
- [x] `TwinWorkflowGraph` + `pipeline_fitness()`
- [x] Minimal evolution 结果
- [x] ~3 个 tests

---

## E5: TwinState Curator (2 天)

### 目标

定期重校准 TwinState 参数，基于行为数据而非自我报告。

### Step 5.1: TwinStateCurator core (0.75 天)

**文件**: `src/twin_runtime/application/calibration/twin_curator.py`（新建）

### Step 5.2: _infer_axis_from_behavior (0.75 天)

**核心算法**（spec #51，修正 E-P4）：

```python
def _infer_axis_from_behavior(self, outcomes, traces, current_twin) -> Dict[str, float]:
    adjustments = {}

    # 修正 E-P4: stakes 从 trace.situation_frame dict 中提取
    def _get_stakes(trace) -> Optional[str]:
        sf = trace.situation_frame  # Dict（model_dump 后的结果）
        if not sf:
            return None
        sfv = sf.get("situation_feature_vector", {})
        return sfv.get("stakes")

    # risk_tolerance: 高风险场景中选择激进选项的比例
    risk_outcomes = []
    for o, t in zip(outcomes, traces):
        stakes = _get_stakes(t)
        if stakes in ("high", "critical"):
            risk_outcomes.append((o, t))

    if len(risk_outcomes) >= 10:
        aggressive_ratio = sum(
            1 for o, t in risk_outcomes
            if self._is_aggressive_choice(o, t)
        ) / len(risk_outcomes)

    # ...

def _is_aggressive_choice(self, outcome: OutcomeRecord, trace) -> bool:
    """修正 E-P13: 定义"激进选项"。

    一个选择被视为激进，当以下任一条件满足：
    1. 用户实际选择在 twin 的 option_ranking 中排名靠后（rank > 1），
       说明 twin 认为这不是最安全的选项但用户仍然选了
    2. trace 的 head_assessments 中多数 head 不推荐该选项（>50% heads 排它 >1）

    如果 trace 信息不足以判断，默认返回 False（保守）。
    """
    if not trace.head_assessments:
        return False
    actual = outcome.actual_choice.lower().strip()
    # 统计多少 head 把 actual_choice 排在第一
    top_picks = sum(
        1 for ha in trace.head_assessments
        if ha.option_ranking and ha.option_ranking[0].lower().strip() == actual
    )
    # 如果大多数 head 不推荐这个选项，认为是激进选择
    return top_picks < len(trace.head_assessments) / 2
        current = current_twin.shared_decision_core.risk_tolerance
        delta = (aggressive_ratio - current) * 0.1  # learning_rate = 0.1
        if abs(delta) > 0.05:
            adjustments["risk_tolerance"] = max(0.0, min(1.0, current + delta))

    # 类似处理 ambiguity_tolerance, action_threshold
    # ...

    # 枚举值（ConflictStyle, ControlOrientation）不自动调整
    return adjustments
```

### Step 5.3: CLI recalibrate (0.25 天)

```
twin-runtime recalibrate [--force]
```

### Step 5.4: 自动提示集成 (0.25 天)

在 cmd_reflect 和 cmd_evaluate 末尾检查 outcome count，每 50 个输出提示。

### Step 5.5: 测试

| 测试 | 断言 |
|------|------|
| `test_infer_risk_tolerance` | 10 个高风险场景 + 8 个选激进 → risk_tolerance 上调 |
| `test_stakes_extracted_from_situation_frame` | 从 dict 正确提取 stakes |
| `test_small_sample_no_update` | <10 outcomes → 不更新 |
| `test_small_delta_no_update` | delta < 0.05 → 不更新 |
| `test_state_version_incremented` | recalibrate 后 version +1 |
| `test_enum_not_auto_adjusted` | ConflictStyle 保持不变 |
| `test_recalibrate_prompt` | 第 50 个 outcome 后输出提示 |

### 交付物

- [x] `TwinStateCurator` class
- [x] `_infer_axis_from_behavior()` — 从 trace.situation_frame dict 提取 stakes
- [x] CLI `twin-runtime recalibrate`
- [x] 自动提示
- [x] 7 个 tests

---

## 全局测试策略

| Component | Offline | Online |
|-----------|---------|--------|
| E1 DSPy | ~16 | 1 |
| E2 SQLite | ~10 | 0 |
| E3 Mem0 | ~8 | 1 |
| E4 EvoAgentX | ~3 | 1 |
| E5 Curator | ~7 | 0 |
| **Total** | **~44** | **3** |

### 文档

每个 component 完成后更新 CHANGELOG。E 全部完成后更新 README "Architecture" section 加 SQLite/Mem0/DSPy。

### 回归测试

所有现有测试在 SQLite backend 下也必须通过。CI matrix:

```yaml
strategy:
  matrix:
    storage_backend: [json, sqlite]
```

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| DSPy adapter 的 trace → stage 输入重建不准 | E1 效果差 | Step 1.5b 优先验证 SI stage，确认路径后再做其他 |
| Step 1.5b 超 1 天（关键路径难点） | E1 延期 | 从 1.9 holdout 借 0.25 天 buffer |
| DSPy BootstrapFewShot 在小数据 (<50) 上效果差 | E1 CF 提升不达标 | 降级为 MIPRO 或手动 few-shot |
| Mem0 API 变更或不稳定 | E3 延期 | merge-on-load + retry 保证可用 |
| Mem0 sync diff 的 get_all 在大量 entries 时超时 | E3 性能 | Step 3.3 分页支持 |
| _is_aggressive_choice 定义不准 | E5 推断偏差 | learning_rate=0.1 限制偏移；需用户 recalibrate 确认 |

---

## 里程碑（修正 E-P7：E4 从 Day 6 开始）

| 日 | Track A | Track B |
|----|---------|---------|
| Day 1 | E1: 1.1-1.3 (env + model + training) | E2: 2.1-2.2 (schema + SqliteOutcome) |
| Day 2 | E1: 1.4-1.5 (metric + DSPy adapters) | E2: 2.3-2.5 (SqliteTrace + migrate + perf) |
| Day 3 | E1: 1.5b-1.6 (转换 + optimizer) | E3: 3.1-3.3 (Protocol + Mem0 + Letta) |
| Day 4 | E1: 1.7 (client 层注入) + 1.8 (CLI) | E3: 3.4-3.5 + E5: 5.1-5.2 |
| Day 5 | E1: 1.9 (holdout) | E5: 5.3-5.5 + 回归测试（E1 在 SQLite 下） |
| Day 6 | E4: 4.1-4.2 (调研 + graph) | Buffer / 文档 |
| Day 7 | E4: 4.3-4.5 (fitness + evolution + report) | Go/No-Go 决策 |
