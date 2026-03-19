# BCDE 宏观路线 + B（Bootstrap Protocol）详细 Spec

---

## 第一部分：BCDE 宏观概览

> 每个 phase 一段话说清楚做什么、交付什么、依赖什么。

### B — Bootstrap Protocol（Week 1-2）

解决冷启动：新用户 15 分钟内获得一个可用的 twin，calibration loop 从 Day 0 就能转。交付 4 个组件：Onboarding interview flow、ExperienceLibrary 数据结构 + 初始填充、ReflectionGenerator（每次 reflect 时生成语义经验条目，借鉴 FLEX critic.py）、Self-Refine ConsistencyChecker（Decision Synthesizer 输出前做一轮 consistency check）。依赖 A 的 ComparisonExecutor 做 before/after CF 展示。

### D — Implicit Reflection + OpenClaw Skill（Week 3-4）

解决 flywheel 自动转：让 calibration loop 不依赖用户手动 `twin-runtime reflect`。交付 4 个组件：OpenClaw SKILL.md + ClawHub 发布、Heartbeat implicit reflection（从 Git/Calendar/Email 推断决策）、ExperienceUpdater（借鉴 FLEX updater.py，冲突感知的经验入库）、Hard-case pattern mining（每 20 次决策扫描系统性偏差，借鉴 MemSkill designer）。依赖 B 的 ExperienceLibrary 和 ReflectionGenerator。

### C — Shadow Mode Demo + Trajectory Viz（Week 5-6）

解决 demo 说服力：让投资人 30 秒内感受到价值，并看到 flywheel 在转的视觉证据。交付 3 个组件：Shadow Mode Claude Code skill（用户工作时 twin 实时预测 + 确认/纠正）、Fidelity trajectory chart（CF vs decision count + CF vs experience count，借鉴 FLEX 的 experience scaling law）、Investor demo 脚本（5 分钟 live demo 流程）。依赖 A 的 comparison data + B 的 self-refine + D 的 implicit reflection 数据。

### E/F — Post-Demo 持续进化（融资后）

E：DSPy/GEPA prompt 自动优化 + EvoAgentX workflow 进化 + SELAUR-lite 升级为 full uncertainty RL。F：TwinState Curator 自动维护（借鉴 Letta memory subagent）+ User Study（5-10 人 × 2 weeks）+ EvidenceStore adapters（Mem0/Letta/Git）。融资后执行，当前只做概念设计不写 spec。

---

## 第二部分：FLEX 工程经验借鉴总结

### 可直接复用的 3 个模块

| FLEX 文件 | CalTwin 对应模块 | 复用方式 | 复用度 |
|-----------|-----------------|---------|-------|
| `critic.py` | ReflectionGenerator (B3) | 抄 prompt 结构和输出 schema，改成 judgment domain | 60% |
| `updater.py` | ExperienceUpdater (D) | 抄冲突检测和去重逻辑，去掉 math/chem 验证 | 50% |
| `explib.py` | ExperienceLibrary (B2) | 抄 JSON 读写和索引结构，加 weight 和 time-decay | 70% |

### 不需要的部分

`reject_sampling.py`（你没有可自动验证的 ground truth）和 `actor.py`（你有自己的 pipeline）不复用。

---

## 第三部分：B（Bootstrap Protocol）详细 Spec

> **Status**: Draft
> **Scope**: 冷启动子系统
> **前置依赖**: A（A/B Baseline Runner）
> **产出**: `twin-runtime bootstrap` 命令 + ExperienceLibrary + ReflectionGenerator + ConsistencyChecker
> **预估工期**: 8-10 天
> **架构决策（已确认）**: ExperienceLibrary 独立文件 / Self-Refine 仅 S2 / ReflectionGenerator CF-miss 才 full extraction / SELAUR-lite n=3 仅 S2

### 验收 Checklist

- [ ] `twin-runtime bootstrap` 交互问答完整可走通
- [ ] 12 + 5 + 3 问题覆盖 5 个决策轴
- [ ] TwinState axis values 合理，reliability = 0.4
- [ ] ExperienceLibrary 初始 15-20 条 entries
- [ ] `twin-runtime reflect` CF miss → 新 ExperienceEntry
- [ ] `twin-runtime reflect` CF hit → confirmation_count += 1
- [ ] ConsistencyChecker 仅 S2 触发，S1 不触发
- [ ] ConsistencyChecker 不改推荐选项，只调 confidence
- [ ] Mini A/B comparison 自动运行
- [ ] ExperienceLibrary 持久化到 `~/.twin-runtime/experience_library.json`
- [ ] Offline tests 全绿
- [ ] Online tests 通过
- [ ] README + CHANGELOG 更新
