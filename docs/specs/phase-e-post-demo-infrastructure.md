# Spec: E — Post-Demo Infrastructure

> **Status**: v5（v2 4 项 + v3 8 项 + v4 7 项 + v5 5 项修正）
> **项目**: twin-runtime
> **前置依赖**: C（Shadow Mode Demo）+ 融资完成
> **预估工期**: 9-11 天（融资后启动；修正 #50 E1 +1 天）

### Review 修正记录

**v2 修正（4 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 8 | 高 | E3 混淆 EvidenceStore 和 ExperienceLibrary | Mem0 接 ExperienceLibraryStore 而非 EvidenceStorePort |
| 9 | 中 | E4 EvoAgentX 3 天不现实 | 改为调研+prototype 2 天，生产集成另算 |
| 10 | 中 | E2 ExperienceLibrary JSON-in-SQLite 无意义 | 选择性迁移：只迁 Outcome/Trace，Experience 保持 JSON |
| 11 | 低 | E 执行顺序 E1/E2 可以并行 | 调整为 E1‖E2 → E3 → E5 → E4 |

**v3 修正（8 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 20 | 高 | E3 引用 ExperienceLibraryStorePort 但该 Protocol 不存在 | E3 前置步骤：在 domain/ports/ 新增 ExperienceLibraryStorePort |
| 21 | 高 | E2 SqliteOutcomeStore SQL INSERT 字段名与 OutcomeRecord 模型不匹配 | 修正为实际字段 outcome_source / created_at |
| 22 | 中 | E3 依赖 E2 的理由不成立（Mem0 local cache 是 JSON，与 SQLite 无关） | E3 独立于 E2，可与 E1/E2 并行 |
| 23 | 中 | E5 "每 50 outcomes 自动触发" 机制未说明触发点 | v1 纯 CLI 手动触发，CLI 输出提示 |
| 24 | 中 | E1 DSPy metric 函数和 TrainingExample 数据模型未定义 | 给出签名和模型 |
| 25 | 低 | E2 append-only 语义与 CalibrationStore 的 promote candidate UPDATE 冲突 | 明确 append-only 范围仅限 outcomes/traces 表 |
| 26 | 低 | E4 cost 估算偏低（未乘以 pipeline 内的 LLM 调用次数） | 修正：2000 pipeline runs × ~5 LLM calls = ~10000 API calls |
| 27 | 低 | E2 OutcomeStorePort 已存在但 spec 中类名对不上 | 对齐实际 Protocol 名称 OutcomeStore |

**v4 修正（7 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 37 | 高 | OutcomeStore Port list_outcomes 缺少 limit，SQLite 加 limit 会破坏 Protocol 兼容性 | Port 签名已加 limit=500（代码已修复） |
| 38 | 中 | cf_metric 双向 `in` 匹配不精确（"redis" in "Use Redis..."误判） | 复用 fidelity_evaluator.choice_similarity |
| 39 | 中 | E5 依赖 E2 不一定必要：早期用户 <500 outcomes 时 JSON 够快 | E5 降为弱依赖，标注可选 |
| 40 | 中 | E1 build_training_set 跳过 PARTIAL（rank>1）丢弃了有价值的错误案例 | 保留所有有 ground truth 的 outcome |
| 41 | 中 | E3 Mem0ExperienceStore 引用 JsonExperienceLibraryStore（不存在）+ 构造函数签名错误 | 修正为 ExperienceLibraryStore(base_dir, user_id) |
| 42 | 中 | E3 Protocol 只有 load/save，无法暴露 Mem0 语义检索优势 | 说明：语义检索通过 load() → 内存 search 实现，Protocol 不扩展 |
| 43 | 低 | E2 migrate --to json 反向迁移数据流未描述 | 补充 SQLite → JSON 全量导出说明 |

**v5 修正（5 项）**

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 50 | 高 | E1 DSPy BootstrapFewShot 需要 DSPy Module，但现有 pipeline 是直接 Anthropic SDK 调用，无法直接使用 | 新增 DSPy 适配层说明，每个 stage 包装为 DSPy Module；工期 +1 天 |
| 51 | 中 | E5 "re-bootstrap using experience data" 算法未定义，无法评估工期 | 定义行为推断算法：统计 outcome 中的 axis 相关特征，与当前 axis value 对比调整 |
| 52 | 中 | E3 Mem0 load() 优先远程 → 远程 save 失败时返回过期数据 | 反转为 local-first，Mem0 仅用于跨设备同步（新设备首次启动时） |
| 53 | 中 | E3 叙事 "Mem0 solves recall, we solve judgment" 与实际集成不符：Mem0 语义搜索未被使用 | 诚实定位：E3 v1 是跨设备同步，语义检索 Protocol 扩展明确 deferred 到 E3 v2 |
| 54 | 低 | E4 成本估算未考虑实际 token 量（~1K input + 500 output per call） | 基于 Sonnet 定价重新估算 |

---

## E 的定位

E 是**post-demo 基础设施**。demo 证明了 flywheel 可行后，E 补齐生产级持久化、prompt 优化、外部 memory 集成。E 的所有组件对 demo 非必要，但对真实用户部署是必要的。

---

## E1: DSPy / GEPA Prompt Optimization

### 问题

当前 pipeline 的 3 个 LLM stage（Situation Interpreter、Head Activation、Decision Synthesizer）使用手写 prompt。随着 ExperienceLibrary 增长和 domain 扩展，手写 prompt 的维护成本指数级增长。

### 方案

用 DSPy 或 GEPA 自动优化 prompt：

```python
# src/twin_runtime/application/optimization/prompt_optimizer.py

class TrainingExample(BaseModel):
    """从 OutcomeStore 构造的训练样本（修正 #24）。"""
    query: str
    option_set: List[str]
    ground_truth_choice: str
    domain: DomainEnum
    stakes: OrdinalTriLevel
    trace_id: str                    # 原始 trace 用于回溯


def cf_metric(example: TrainingExample, prediction: Dict[str, Any]) -> float:
    """Choice Fidelity metric for DSPy optimization（修正 #24 #38）。

    复用 fidelity_evaluator.choice_similarity 进行规范化匹配，
    而非简陋的双向 `in` 操作（修正 #38：避免 "redis" in "Use Redis" 误判）。
    """
    from twin_runtime.application.calibration.fidelity_evaluator import choice_similarity
    ranking = prediction.get("option_ranking", [])
    if not ranking:
        return 0.0
    score, rank = choice_similarity(ranking, example.ground_truth_choice)
    if rank == 1:
        return 1.0
    elif rank == 2:
        return 0.5
    return 0.0


class PromptOptimizer:
    """
    用 DSPy 的 BootstrapFewShot 或 MIPRO 优化 pipeline prompt。
    输入：一组带 ground truth 的场景（从 OutcomeStore 获取）。
    输出：优化后的 prompt template（存入 prompt_store）。
    """

    def __init__(self, framework: str = "dspy"):
        self._framework = framework  # "dspy" or "gepa"

    def build_training_set(
        self,
        outcome_store,
        trace_store,
        min_examples: int = 20,
    ) -> List[TrainingExample]:
        """从 OutcomeStore + TraceStore 构造训练集。

        修正 #40: 保留所有有 ground truth 的 outcome（HIT + MISS + PARTIAL）。
        PARTIAL (rank > 1) 是 twin 预测错误的案例——恰好是最有价值的训练数据。
        只跳过 outcome_source 不可靠的记录（如 implicit_file 置信度过低）。
        """
        ...

    def optimize(
        self,
        stage: str,              # "situation_interpreter" / "head_activation" / "decision_synthesizer"
        training_set: List[TrainingExample],
        metric: Callable = cf_metric,
        num_trials: int = 50,
    ) -> OptimizedPrompt:
        ...
```

### DSPy 适配层（修正 #50）

当前 pipeline 的 3 个 LLM stage 直接调用 `LLMPort.ask_json()` / `ask_structured()`，不是 DSPy Module。DSPy 的 BootstrapFewShot 和 MIPRO 需要 `dspy.Module` + `dspy.Signature` 才能工作。

**解决方案**：为每个 stage 编写 DSPy adapter wrapper，不修改现有 pipeline 代码：

```python
# src/twin_runtime/application/optimization/dspy_adapters.py

import dspy

class SituationInterpreterSignature(dspy.Signature):
    """Interpret a user query into a situation frame."""
    query: str = dspy.InputField()
    domain_keywords: str = dspy.InputField()
    situation_frame: str = dspy.OutputField(desc="JSON situation frame")

class SituationInterpreterModule(dspy.Module):
    """DSPy wrapper around situation_interpreter.interpret_situation."""
    def __init__(self):
        super().__init__()
        self.interpret = dspy.Predict(SituationInterpreterSignature)

    def forward(self, query, domain_keywords):
        return self.interpret(query=query, domain_keywords=domain_keywords)

# 类似 adapter 用于 HeadActivationModule 和 DecisionSynthesizerModule
```

优化后的 prompt（含 few-shot examples）导出为 JSON，pipeline 启动时注入到现有 `ask_json()` 调用的 system prompt 前缀中。这样既利用了 DSPy 的优化能力，又不破坏现有 pipeline 架构。

### 触发

```
twin-runtime optimize --stage situation_interpreter
    [--trials 50]
    [--min-training-examples 20]
```

自动触发：当 OutcomeStore 积累 ≥ 50 个 outcomes 时，CLI 输出提示 "Consider running `twin-runtime optimize`"。

### 集成

优化后的 prompt 存入 `~/.twin-runtime/store/<user_id>/prompts/<stage>.json`。Pipeline 启动时检查是否有优化版本，有则使用。

### 工期：4 天（修正 #50：+1 天 DSPy adapter 层）

---

## E2: SQLite Append-Only Persistence

### 问题

当前所有 store（TwinStore、OutcomeStore、TraceStore、ExperienceLibraryStore）使用 JSON 文件。超过 ~500 条 outcome 后，JSON 的读写性能和并发安全性不足。

### 方案（修正 #10 #25：选择性迁移，限定 append-only 范围）

只对 OutcomeStore 和 TraceStore 用 SQLite（高频 append + range query）。ExperienceLibrary 保持 JSON 文件（规模小，几百条 entry，不需要 SQL 查询能力）。

**append-only 范围（修正 #25）**：仅限 outcomes 表和 traces 表。CalibrationStore 的其他操作（candidate promote 等包含 UPDATE 语义）继续使用 JSON 文件。未来如需迁移 CalibrationStore 到 SQLite，应使用 event-sourcing 模式将 UPDATE 改为 INSERT event。

```python
# src/twin_runtime/infrastructure/backends/sqlite/

class SqliteOutcomeStore:
    """
    SQLite 实现 OutcomeStore Protocol。
    append-only：INSERT only，no UPDATE/DELETE。
    每个 user_id 一个 .db 文件。

    实现的 Protocol（修正 #27）：
        domain.ports.calibration_store.OutcomeStore
    """

    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path)
        self._ensure_schema()

    def save_outcome(self, outcome: OutcomeRecord) -> str:
        # 修正 #21: 使用 OutcomeRecord 的实际字段名
        self._db.execute(
            "INSERT INTO outcomes (outcome_id, trace_id, actual_choice, "
            "outcome_source, created_at, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outcome.outcome_id, outcome.trace_id, outcome.actual_choice,
             outcome.outcome_source.value, outcome.created_at.isoformat(),
             outcome.model_dump_json()),
        )
        self._db.commit()
        return outcome.outcome_id

    def list_outcomes(self, trace_id: Optional[str] = None,
                      *, limit: int = 500) -> List[OutcomeRecord]:
        # 修正 #37: limit 参数与 Port 签名对齐（Port 已更新）
        if trace_id:
            rows = self._db.execute(
                "SELECT data_json FROM outcomes WHERE trace_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT data_json FROM outcomes "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [OutcomeRecord.model_validate_json(r[0]) for r in rows]


class SqliteTraceStore:
    """
    SQLite 实现 TraceStore Protocol。
    append-only。支持 range query by timestamp。

    实现的 Protocol：
        domain.ports.trace_store.TraceStore
    """
    ...

# 注意：不做 SqliteExperienceStore 和 SqliteCalibrationStore。
# ExperienceLibrary 继续用 JSON 文件——它的规模（几百条 entry）
# 不需要 SQLite 的查询能力。
# CalibrationStore 的 candidate promote 包含 UPDATE 语义，
# 不适合 append-only SQLite。
```

### 迁移

```
twin-runtime migrate --to sqlite     # JSON → SQLite 一键迁移（仅 outcome + trace）
twin-runtime migrate --to json       # SQLite → JSON 回退
```

**反向迁移 SQLite → JSON（修正 #43）**：`migrate --to json` 从 SQLite 全量读取所有 outcomes 和 traces，逐条写入 JSON 文件。因为 SQLite 是 append-only 的数据源（没有 UPDATE），导出的 JSON 文件是精确副本。迁移后自动切换 config 中的 `storage_backend`，但不删除 SQLite 文件（用户需手动清理）。

Config 中新增 `storage_backend: "json" | "sqlite"`。

### 工期：2 天

---

## E3: Mem0 / Letta ExperienceLibrary Adapters

### 问题

当前 ExperienceLibrary 是本地 JSON。接入 Mem0（cloud memory layer）可以让 twin 跨设备共享 experience，并利用 Mem0 的语义检索。Letta 提供类似能力但更偏 agent framework。

### 关键区分（修正 #8）

twin-runtime 有两种不同的存储：

- **EvidenceStore**：存 EvidenceFragment（从 Notion/Gmail/Calendar/Git 扫描来的原始数据）
- **ExperienceLibrary**：存 ExperienceEntry + PatternInsight（从反思中提炼的经验）

Mem0 的语义检索适合后者（经验条目），不是前者（原始证据碎片）。所以 Mem0 应该实现 **ExperienceLibraryStore** 接口，不是 EvidenceStorePort。

### 前置步骤（修正 #20：新增 Port Protocol）

当前 `ExperienceLibraryStore` 是具体类（`infrastructure/backends/json_file/experience_store.py`），没有对应的 Protocol 定义。E3 的第一步需要抽取 Port：

```python
# domain/ports/experience_store.py — 新增

@runtime_checkable
class ExperienceLibraryStore(Protocol):
    """Store experience library (entries + patterns)."""
    def load(self) -> ExperienceLibrary: ...
    def save(self, library: ExperienceLibrary) -> None: ...
```

然后让现有 JSON 实现和新的 Mem0 实现都符合这个 Protocol。

### 方案

```python
# src/twin_runtime/infrastructure/backends/mem0/
class Mem0ExperienceStore:
    """
    用 Mem0 API 作为 ExperienceLibrary backend。
    实现 domain.ports.experience_store.ExperienceLibraryStore Protocol。

    save() → 本地 JSON 写入 + 增量同步到 Mem0（best-effort）
    load() → 本地 JSON 优先（修正 #52：always most recent due to write-through）
             Mem0 仅在本地文件不存在时使用（新设备首次同步）

    修正 #53: E3 v1 定位为**跨设备同步层**，不是语义搜索层。
    语义检索仍通过内存中 library.search_entries() 实现（keyword overlap）。
    扩展 Protocol 以支持 Mem0 原生语义搜索 deferred 到 E3 v2。
    """

    def __init__(self, mem0_api_key: str, user_id: str,
                 store_dir: str):
        from mem0 import MemoryClient
        self._client = MemoryClient(api_key=mem0_api_key)
        self._user_id = user_id
        # 修正 #41: 正确的类名和构造函数签名
        from twin_runtime.infrastructure.backends.json_file.experience_store import (
            ExperienceLibraryStore,
        )
        self._local = ExperienceLibraryStore(store_dir, user_id)  # write-through cache

    def save(self, library: ExperienceLibrary) -> None:
        self._local.save(library)  # always write local first
        self._sync_to_mem0(library)  # best-effort remote sync

    def load(self) -> ExperienceLibrary:
        # 修正 #52: local-first — local 总是最新的（write-through 保证）
        # Mem0 仅在本地不存在时使用（新设备首次同步场景）
        local_lib = self._local.load()
        if local_lib.size > 0:
            return local_lib
        try:
            return self._load_from_mem0()
        except Exception:
            return local_lib  # empty but safe

# src/twin_runtime/infrastructure/backends/letta/
class LettaExperienceStore:
    """Letta agent memory 作为 ExperienceLibrary backend。
    实现 ExperienceLibraryStore Protocol。"""
    ...
```

### 配置

```
twin-runtime config set experience_backend mem0
twin-runtime config set mem0_api_key sk-xxx
```

### 对投资人的叙事

"Mem0 solves recall, we solve judgment. We sit on top." 这个叙事在 C demo 中口头讲。

**修正 #53：诚实定位**。E3 v1 实际实现的是跨设备同步（write-through cache + Mem0 remote backup），不是 Mem0 的语义搜索集成。Mem0 原生语义检索的真正优势需要扩展 ExperienceLibraryStore Protocol 添加 `search(query, top_k)` 方法，这涉及对 pipeline 的 evidence retrieval 路径改造，deferred 到 E3 v2（post-user-study）。

### 工期：2 天（含 Protocol 抽取 0.5 天）

---

## E4: EvoAgentX Workflow Evolution

### 问题

当前 pipeline 的 6 个 stage 是固定序列。EvoAgentX 可以用进化算法发现更优的 stage 组合和路由策略。

### 方案

将 pipeline 表示为 EvoAgentX 的 workflow graph，用 CF 作为 fitness function 进化：

```python
# src/twin_runtime/application/optimization/workflow_evolver.py

class WorkflowEvolver:
    """
    用 EvoAgentX 进化 pipeline workflow。
    每个 individual = 一组 stage 配置（哪些 stage 启用、S1/S2 阈值、Head 权重等）。
    Fitness = CF on holdout set。
    """

    def evolve(
        self,
        population_size: int = 20,
        generations: int = 10,
        holdout_scenarios: List[EvalScenario],
    ) -> EvolvedWorkflow:
        ...
```

### 工期（修正 #9：分阶段）

**阶段 1：调研 + prototype（2 天）** — 验证 EvoAgentX API 稳定性，跑一个 minimal 进化（5 individuals × 3 代 × 5 scenarios = 75 pipeline runs），评估是否有统计显著的 CF 提升。

**阶段 2：生产集成（3 天，仅在 prototype 有效时追加）** — 完整 pipeline graph 表示、config 导出、CI 集成。

**成本估算（修正 #26）**：每次 pipeline run 包含 ~5 次 LLM API 调用（interpret + N heads + synthesize）。

- Prototype: 75 pipeline runs × ~5 = ~375 API calls，成本约 $1-5
- 生产规模: 2000 pipeline runs × ~5 = ~10000 API calls

**修正 #54：基于 Sonnet 定价重新估算**：假设平均每次 API call ~1K input + 500 output tokens，Sonnet 定价 $3/M input + $15/M output：
- Input: 10000 × 1K = 10M tokens → $30
- Output: 10000 × 500 = 5M tokens → $75
- **总计约 $100-$120**（非之前估计的 $25-75）

---

## E5: TwinState Curator

### 问题

TwinState 的参数（risk_tolerance、action_threshold 等）在 bootstrap 后只由 ReflectionGenerator 间接更新（通过 ExperienceLibrary）。没有定期重校准机制。

### 方案

```python
# src/twin_runtime/application/calibration/twin_curator.py

class TwinStateCurator:
    """
    定期（每 50 个 outcomes）重新校准 TwinState 参数。
    1. 从 outcomes 计算 per-domain CF
    2. 对 CF 低的 domain 调整 head_reliability（向下修正）
    3. 更新 axis values 基于行为数据（而非自我报告）
    4. 更新 state_version
    """

    def recalibrate(self, user_id: str) -> TwinState:
        ...

    def _infer_axis_from_behavior(
        self, outcomes: List[OutcomeRecord], traces: List[RuntimeDecisionTrace],
        current_twin: TwinState,
    ) -> Dict[str, float]:
        """修正 #51: 行为推断 axis 值的算法。

        不是 "re-bootstrap"（那需要问答），而是从 outcome 行为模式推断：

        1. 分组：按 domain 对 outcomes 分组
        2. 统计 axis 相关特征：
           - risk_tolerance: 用户在高风险场景中选择激进选项的比例
           - ambiguity_tolerance: 用户在高不确定性场景中做决策的速度
           - action_threshold: 用户倾向于"行动"vs"等待"选项的比例
        3. 对比：行为推断值 vs 当前 TwinState axis 值
        4. 调整：delta = (inferred - current) × learning_rate (0.1)
           仅当 |delta| > 0.05 且有 ≥10 个相关 outcome 时才更新
           （防止小样本过拟合）

        数据源：trace.situation_feature_vector（stakes, reversibility）
                + outcome.actual_choice（选了什么）
                + trace.option_ranking（twin 怎么排的）

        限制：只调整 SharedDecisionCore 的数值 axis。
        ConflictStyle、ControlOrientation 等枚举值不自动调整——
        需要显著证据（>50 outcomes 且分布明显偏离），通过 LLM 确认后修改。
        """
        ...
```

### 触发机制（修正 #23：v1 纯 CLI + 提示）

v1 使用纯 CLI 手动触发，配合自动提示：

```
twin-runtime recalibrate [--force]
```

**自动提示**：在 `cmd_reflect` 和 `cmd_evaluate` 完成后，检查 OutcomeStore 中的 outcome 总数。如果 `total % 50 == 0`，输出提示：

```
💡 You now have 50 outcomes. Consider running `twin-runtime recalibrate` to update TwinState parameters.
```

不自动执行 recalibrate（避免意外修改 TwinState）。未来版本可考虑在 heartbeat 中加入 curator check。

### 工期：2 天

---

## E 优先级与依赖（修正 #11 #22：E3 独立于 E2）

```
E1 (DSPy) ←── 独立，需 ≥50 outcomes
E2 (SQLite) ← 独立，越早做越好
E3 (Mem0/Letta) ← 独立（修正 #22：local cache 是 JSON，与 E2 SQLite 无关）
  ↓
E1‖E2‖E3 并行启动
  ↓
E5 (TwinCurator) ← 弱依赖 E2（修正 #39：<500 outcomes 时 JSON 够快，E2 是性能优化非前置条件）
E4 (EvoAgentX) ← 依赖 E1（优化后的 prompt 作为进化种子）；仅在 prototype 验证有效后追加
```

建议执行顺序：**E1‖E2‖E3‖E5 并行** → E4

修正 #39: E5 降为弱依赖 E2。早期用户 outcome 数量 <500 时，JSON CalibrationStore.list_outcomes() 性能足够（<100ms）。E5 可以在 JSON backend 上先开发和测试，E2 完成后自动受益于 SQLite 的查询性能。

E3 不依赖 E2 的原因（修正 #22）：E3 的 Mem0ExperienceStore 使用本地 JSON 作为 write-through cache（`ExperienceLibraryStore`），而 E2 明确不迁移 ExperienceLibrary 到 SQLite。两者的存储对象完全不同（E2: outcomes/traces; E3: experience entries）。

---

## E 验收 Checklist

**E1: Prompt Optimization（修正 #50：含 DSPy adapter 层）**
- [ ] DSPy adapter: 3 个 stage 各有 Signature + Module wrapper
- [ ] 优化后 prompt（含 few-shot examples）导出为 JSON，注入到现有 ask_json() 前缀
- [ ] TrainingExample 模型定义 + OutcomeStore → TrainingSet 构造
- [ ] build_training_set 保留所有 outcome（HIT + MISS + PARTIAL，不跳过 rank>1）
- [ ] cf_metric 使用 choice_similarity（非双向 `in` 操作）
- [ ] DSPy BootstrapFewShot 对 3 个 stage 各优化成功
- [ ] 优化后 prompt 存入 prompt_store
- [ ] Pipeline 自动检测并使用优化版 prompt
- [ ] CF 提升 ≥ 3pp（在 holdout set 上）
- [ ] `twin-runtime optimize` CLI 可用

**E2: SQLite Persistence（修正 #10 #25 #37 #43：选择性迁移）**
- [ ] SqliteOutcomeStore 实现 OutcomeStore Protocol（字段名对齐：outcome_source, created_at）
- [ ] SqliteTraceStore 实现 TraceStore Protocol
- [ ] list_outcomes limit 参数与 Port 签名对齐（limit=500）
- [ ] append-only 范围限定于 outcomes/traces 表（CalibrationStore 其他操作仍用 JSON）
- [ ] `twin-runtime migrate --to sqlite` 一键迁移（仅 outcome + trace）
- [ ] `twin-runtime migrate --to json` 反向迁移：SQLite 全量导出到 JSON
- [ ] 性能测试：1000 outcomes 下 read/write < 50ms
- [ ] 所有现有测试在 SQLite backend 下通过
- [ ] ExperienceLibrary 继续用 JSON 文件（不迁移）

**E3: Mem0/Letta Adapters（修正 #8 #20 #41 #52 #53：跨设备同步 v1）**
- [ ] `domain/ports/experience_store.py` 新增 ExperienceLibraryStore Protocol（load/save）
- [ ] 现有 ExperienceLibraryStore 符合新 Protocol（无需改代码，duck typing）
- [ ] Mem0ExperienceStore 实现 Protocol（构造函数：mem0_api_key, user_id, store_dir）
- [ ] LettaExperienceStore 实现 Protocol
- [ ] Write-through cache：local-first load，Mem0 仅用于新设备首次同步
- [ ] save() 先写本地，再 best-effort 同步到 Mem0
- [ ] `twin-runtime config set experience_backend mem0` 可用
- [ ] 降级：Mem0 API 不可用时 fallback 到本地 JSON
- [ ] 文档明确：E3 v1 = 跨设备同步，语义检索 deferred 到 E3 v2

**E4: Workflow Evolution（修正 #9 #26：分阶段 + 修正成本）**
- [ ] 阶段 1：EvoAgentX API 调研 + minimal prototype（75 pipeline runs ≈ 375 API calls）
- [ ] Prototype 报告：CF 提升是否统计显著
- [ ] 阶段 2（仅在 prototype 有效时）：完整 pipeline graph + config 导出
- [ ] 最优 workflow 可导出为新的 pipeline config
- [ ] 成本预算：生产规模 ~10000 API calls ≈ $100-120（Sonnet 定价）

**E5: TwinState Curator（修正 #23 #39 #51：行为推断算法定义）**
- [ ] `twin-runtime recalibrate [--force]` CLI 可用
- [ ] cmd_reflect / cmd_evaluate 中自动提示（每 50 outcomes）
- [ ] Per-domain CF 计算正确
- [ ] _infer_axis_from_behavior: 从 outcome 行为模式推断 axis 值（非 re-bootstrap）
- [ ] 仅在 |delta| > 0.05 且 ≥10 个相关 outcome 时才更新（防止小样本过拟合）
- [ ] 枚举值（ConflictStyle 等）不自动调整，需 LLM 确认
- [ ] state_version 递增
- [ ] JSON backend 下可正常运行（不强依赖 SQLite）

---

## 后续衔接

C → demo → 融资 → E

C 完成后立即可以跑 investor demo。demo 数据来自 D 的 implicit reflection 自动积累 + A 的 baseline comparison。demo 结束后进入 E，E1‖E2‖E3‖E5 四项并行启动，然后 E4 在 E1 完成后启动（仅在 prototype 验证有效时）。

E 完成后进入 F（User Study: 5-10 人 × 2 周），使用 E 的 SQLite persistence + Mem0 backend 支持多用户长期使用。
