# Spec: E — Post-Demo Infrastructure

> **Status**: v2（4 corrections applied from review）
> **项目**: twin-runtime
> **前置依赖**: C（Shadow Mode Demo）+ 融资完成
> **预估工期**: 8-10 天（融资后启动）

### Review 修正记录（4 项）

| # | 级别 | 问题 | 修正 |
|---|------|------|------|
| 8 | 高 | E3 混淆 EvidenceStore 和 ExperienceLibrary | Mem0 接 ExperienceLibraryStore 而非 EvidenceStorePort |
| 9 | 中 | E4 EvoAgentX 3 天不现实 | 改为调研+prototype 2 天，生产集成另算 |
| 10 | 中 | E2 ExperienceLibrary JSON-in-SQLite 无意义 | 选择性迁移：只迁 Outcome/Trace，Experience 保持 JSON |
| 11 | 低 | E 执行顺序 E1/E2 可以并行 | 调整为 E1‖E2 → E3 → E5 → E4 |

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

class PromptOptimizer:
    """
    用 DSPy 的 BootstrapFewShot 或 MIPRO 优化 pipeline prompt。
    输入：一组带 ground truth 的场景（从 OutcomeStore 获取）。
    输出：优化后的 prompt template（存入 prompt_store）。
    """

    def __init__(self, framework: str = "dspy"):
        self._framework = framework  # "dspy" or "gepa"

    def optimize(
        self,
        stage: str,              # "situation_interpreter" / "head_activation" / "decision_synthesizer"
        training_set: List[TrainingExample],
        metric: Callable,        # CF or CQ
        num_trials: int = 50,
    ) -> OptimizedPrompt:
        ...
```

### 触发

```
twin-runtime optimize --stage situation_interpreter
    [--trials 50]
    [--min-training-examples 20]
```

自动触发：当 OutcomeStore 积累 ≥ 50 个 outcomes 时，CLI 输出提示 "Consider running `twin-runtime optimize`"。

### 集成

优化后的 prompt 存入 `~/.twin-runtime/store/<user_id>/prompts/<stage>.json`。Pipeline 启动时检查是否有优化版本，有则使用。

### 工期：3 天

---

## E2: SQLite Append-Only Persistence

### 问题

当前所有 store（TwinStore、OutcomeStore、TraceStore、ExperienceLibraryStore）使用 JSON 文件。超过 ~500 条 outcome 后，JSON 的读写性能和并发安全性不足。

### 方案（修正 #10：选择性迁移）

只对 OutcomeStore 和 TraceStore 用 SQLite（高频 append + range query）。ExperienceLibrary 保持 JSON 文件（规模小，几百条 entry，不需要 SQL 查询能力）。

```python
# src/twin_runtime/infrastructure/backends/sqlite/

class SqliteOutcomeStore(OutcomeStorePort):
    """
    SQLite 实现。append-only：INSERT only，no UPDATE/DELETE。
    每个 user_id 一个 .db 文件。
    """

    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path)
        self._ensure_schema()

    def record(self, outcome: OutcomeRecord) -> None:
        self._db.execute(
            "INSERT INTO outcomes (trace_id, actual_choice, source, timestamp, data_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (outcome.trace_id, outcome.actual_choice, outcome.source.value,
             outcome.timestamp.isoformat(), outcome.model_dump_json()),
        )
        self._db.commit()

class SqliteTraceStore(TraceStorePort):
    """同上。traces 表。支持 range query by timestamp。"""
    ...

# 注意：不做 SqliteExperienceStore。
# ExperienceLibrary 继续用 JSON 文件——它的规模（几百条 entry）
# 不需要 SQLite 的查询能力，强行塞进 SQLite 的 JSON column
# 等于用 SQLite 当文件系统，没有获得任何好处。
```

### 迁移

```
twin-runtime migrate --to sqlite     # JSON → SQLite 一键迁移（仅 outcome + trace）
twin-runtime migrate --to json       # 回退
```

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

### 方案

```python
# src/twin_runtime/infrastructure/backends/mem0/
class Mem0ExperienceStore(ExperienceLibraryStorePort):
    """
    用 Mem0 API 作为 ExperienceLibrary backend。
    save() → 增量同步到 Mem0
    load() → 从 Mem0 拉取 + 本地 JSON 作为 write-through cache
    search_entries() → mem0.search()（语义检索，比本地 keyword 匹配更强）
    """

    def __init__(self, mem0_api_key: str, user_id: str,
                 local_fallback_path: Optional[Path] = None):
        from mem0 import MemoryClient
        self._client = MemoryClient(api_key=mem0_api_key)
        self._user_id = user_id
        self._local = JsonExperienceLibraryStore(local_fallback_path)  # write-through cache

    def save(self, library: ExperienceLibrary) -> None:
        self._local.save(library)  # always write local
        self._sync_to_mem0(library)  # best-effort remote

    def load(self) -> ExperienceLibrary:
        try:
            return self._load_from_mem0()
        except Exception:
            return self._local.load()  # fallback

# src/twin_runtime/infrastructure/backends/letta/
class LettaExperienceStore(ExperienceLibraryStorePort):
    """Letta agent memory 作为 ExperienceLibrary backend。"""
    ...
```

### 配置

```
twin-runtime config set experience_backend mem0
twin-runtime config set mem0_api_key sk-xxx
```

### 对投资人的叙事

"Mem0 solves recall, we solve judgment. We sit on top." 这个叙事在 C demo 中口头讲，E3 做技术实现。

### 工期：2 天

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

**阶段 1：调研 + prototype（2 天）** — 验证 EvoAgentX API 稳定性，跑一个 minimal 进化（5 individuals × 3 代 × 5 scenarios = 75 LLM calls），评估是否有统计显著的 CF 提升。

**阶段 2：生产集成（3 天，仅在 prototype 有效时追加）** — 完整 pipeline graph 表示、config 导出、CI 集成。

注意：20 individuals × 10 scenarios × 10 代 = 2000 次 LLM 调用（仅 fitness evaluation），成本约 $5-15。prototype 阶段用小规模验证 ROI。

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
    2. 对 CF 低的 domain 触发 re-bootstrap（用 experience data 代替问答）
    3. 更新 axis values 基于行为数据（而非自我报告）
    4. 更新 state_version
    """

    def recalibrate(self, user_id: str) -> TwinState:
        ...
```

CLI: `twin-runtime recalibrate [--force]`

### 工期：2 天

---

## E 优先级与依赖（修正 #11：E1/E2 可并行）

```
E1 (DSPy) ←── 独立，需 ≥50 outcomes
E2 (SQLite) ← 独立，越早做越好
  ↓
E1‖E2 并行启动
  ↓
E3 (Mem0/Letta) ← 依赖 E2（SQLite 作为 local cache 的并发保证）
E5 (TwinCurator) ← 依赖 E2（需要高效读取大量 outcomes）
E4 (EvoAgentX) ← 依赖 E1（优化后的 prompt 作为进化种子）；仅在 prototype 验证有效后追加
```

建议执行顺序：E1‖E2 → E3 → E5 → E4

---

## E 验收 Checklist

**E1: Prompt Optimization**
- [ ] DSPy BootstrapFewShot 对 3 个 stage 各优化成功
- [ ] 优化后 prompt 存入 prompt_store
- [ ] Pipeline 自动检测并使用优化版 prompt
- [ ] CF 提升 ≥ 3pp（在 holdout set 上）
- [ ] `twin-runtime optimize` CLI 可用

**E2: SQLite Persistence（修正 #10：选择性迁移）**
- [ ] SqliteOutcomeStore / SqliteTraceStore 实现（不含 ExperienceStore）
- [ ] Append-only 语义（no UPDATE/DELETE）
- [ ] `twin-runtime migrate --to sqlite` 一键迁移（仅 outcome + trace）
- [ ] 性能测试：1000 outcomes 下 read/write < 50ms
- [ ] 所有现有测试在 SQLite backend 下通过
- [ ] ExperienceLibrary 继续用 JSON 文件（不迁移）

**E3: Mem0/Letta Adapters（修正 #8：ExperienceLibraryStore）**
- [ ] Mem0ExperienceStore 实现 ExperienceLibraryStorePort（save/load/search_entries）
- [ ] LettaExperienceStore 实现 ExperienceLibraryStorePort
- [ ] Write-through cache：本地 JSON + 远程 Mem0 同步
- [ ] `twin-runtime config set experience_backend mem0` 可用
- [ ] 降级：Mem0 API 不可用时 fallback 到本地 JSON

**E4: Workflow Evolution（修正 #9：分阶段）**
- [ ] 阶段 1：EvoAgentX API 调研 + minimal prototype（5×3×5 = 75 LLM calls）
- [ ] Prototype 报告：CF 提升是否统计显著
- [ ] 阶段 2（仅在 prototype 有效时）：完整 pipeline graph + config 导出
- [ ] 最优 workflow 可导出为新的 pipeline config

**E5: TwinState Curator**
- [ ] 每 50 outcomes 自动触发 recalibrate
- [ ] Per-domain CF 计算正确
- [ ] 低 CF domain 的 axis values 基于行为数据更新
- [ ] `twin-runtime recalibrate` CLI 可用

---

## 后续衔接

C → demo → 融资 → E

C 完成后立即可以跑 investor demo。demo 数据来自 D 的 implicit reflection 自动积累 + A 的 baseline comparison。demo 结束后进入 E，E1‖E2 并行启动，然后 E3 → E5 → E4 顺序补齐生产基础设施。

E 完成后进入 F（User Study: 5-10 人 × 2 周），使用 E 的 SQLite persistence + Mem0 backend 支持多用户长期使用。
