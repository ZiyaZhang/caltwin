"""Bootstrap question definitions for twin-runtime onboarding.

Phase 1: 12 forced-choice questions covering 5 decision-style axes.
Phase 2: 5 domain-expertise self-assessment questions.
Phase 3: 3 open-ended scenario questions for narrative calibration.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    FORCED_CHOICE = "forced_choice"
    SLIDER = "slider"
    OPEN_SCENARIO = "open_scenario"


class BootstrapQuestion(BaseModel):
    id: str
    phase: int = Field(ge=1, le=3)
    type: QuestionType
    question: str
    options: List[str] = Field(default_factory=list)
    axes: Dict[str, List[float]] = Field(default_factory=dict)
    domain: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class BootstrapAnswer(BaseModel):
    question_id: str
    type: QuestionType
    chosen_option: Optional[int] = None
    slider_value: Optional[float] = None
    free_text: Optional[str] = None
    domain: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 1: Forced-choice questions — 12 total, covering 5 axes
# ---------------------------------------------------------------------------

_PHASE1_QUESTIONS: List[BootstrapQuestion] = [
    # ── risk_tolerance (3 questions) ──────────────────────────────────────
    BootstrapQuestion(
        id="p1_risk_01",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="面对一个有30%失败概率但回报很大的机会，你会怎么做？",
        options=["观望等待更多信息", "立即行动抓住机会"],
        axes={"risk_tolerance": [-0.5, 0.5]},
        tags=["risk_tolerance"],
    ),
    BootstrapQuestion(
        id="p1_risk_02",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="朋友邀你合伙做一个新项目，市场前景不确定但团队很强，你倾向于？",
        options=["等市场信号更明确再加入", "相信团队能力，先加入再调整"],
        axes={"risk_tolerance": [-0.5, 0.5]},
        tags=["risk_tolerance"],
    ),
    BootstrapQuestion(
        id="p1_risk_03",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="公司提供两个岗位：一个稳定但成长空间有限，另一个充满挑战但可能被裁撤。你选？",
        options=["选择稳定岗位", "选择高挑战岗位"],
        axes={"risk_tolerance": [-0.5, 0.5]},
        tags=["risk_tolerance"],
    ),
    # ── action_threshold (3 questions) ────────────────────────────────────
    BootstrapQuestion(
        id="p1_action_01",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="当你有70%的信息就可以做决定时，你会怎么做？",
        options=["等到信息更完整再行动", "直接基于现有信息决定"],
        axes={"action_threshold": [-0.5, 0.5]},
        tags=["action_threshold"],
    ),
    BootstrapQuestion(
        id="p1_action_02",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="团队讨论了很久还没有结论，你倾向于？",
        options=["继续讨论直到大家达成一致", "先定一个方向，边做边调整"],
        axes={"action_threshold": [-0.5, 0.5]},
        tags=["action_threshold"],
    ),
    BootstrapQuestion(
        id="p1_action_03",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="你要买一个比较贵的东西，研究了几天还有些细节不确定，你会？",
        options=["再多研究几天，确保没有遗漏", "差不多了解了就下单，用了再说"],
        axes={"action_threshold": [-0.5, 0.5]},
        tags=["action_threshold"],
    ),
    # ── information_threshold (2 questions) ───────────────────────────────
    BootstrapQuestion(
        id="p1_info_01",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="在做重大决定前，你倾向于？",
        options=["广泛收集各方意见", "依靠自己的判断快速决定"],
        axes={"information_threshold": [-0.5, 0.5]},
        tags=["information_threshold"],
    ),
    BootstrapQuestion(
        id="p1_info_02",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="选择旅行目的地时，你通常会？",
        options=["花大量时间看攻略、比较方案", "大方向定了就出发，到了再说"],
        axes={"information_threshold": [-0.5, 0.5]},
        tags=["information_threshold"],
    ),
    # ── conflict_style_proxy (2 questions) ────────────────────────────────
    BootstrapQuestion(
        id="p1_conflict_01",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="当团队对方向有分歧时，你倾向于？",
        options=["寻求妥协让各方都能接受", "坚持自己认为正确的方向"],
        axes={"conflict_style_proxy": [-0.5, 0.5]},
        tags=["conflict_style_proxy"],
    ),
    BootstrapQuestion(
        id="p1_conflict_02",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="朋友推荐的餐厅你觉得一般，但大家都想去，你会？",
        options=["配合大家的选择", "表达自己的真实想法，建议换一家"],
        axes={"conflict_style_proxy": [-0.5, 0.5]},
        tags=["conflict_style_proxy"],
    ),
    # ── explore_exploit_balance (2 questions) ─────────────────────────────
    BootstrapQuestion(
        id="p1_explore_01",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="在工作方法上，你更倾向于？",
        options=["坚持已验证有效的方法", "不断尝试新的工具和方式"],
        axes={"explore_exploit_balance": [-0.5, 0.5]},
        tags=["explore_exploit_balance"],
    ),
    BootstrapQuestion(
        id="p1_explore_02",
        phase=1,
        type=QuestionType.FORCED_CHOICE,
        question="午餐时间，你更可能？",
        options=["去常去的那家店，味道稳定", "试一家新开的店，看看怎么样"],
        axes={"explore_exploit_balance": [-0.5, 0.5]},
        tags=["explore_exploit_balance"],
    ),
]

# ---------------------------------------------------------------------------
# Phase 2: Domain-expertise self-assessment — 5 questions
# ---------------------------------------------------------------------------

_PHASE2_QUESTIONS: List[BootstrapQuestion] = [
    BootstrapQuestion(
        id="p2_domain_work",
        phase=2,
        type=QuestionType.FORCED_CHOICE,
        question="在工作决策方面，你觉得自己的判断可靠度如何？",
        options=[
            "非常可靠，我有大量经验",
            "一般，有些领域不太确定",
            "不太可靠，需要更多经验",
        ],
        domain="work",
        tags=["work"],
    ),
    BootstrapQuestion(
        id="p2_domain_finance",
        phase=2,
        type=QuestionType.FORCED_CHOICE,
        question="在理财和投资决策上，你对自己的判断有多大信心？",
        options=[
            "非常有信心，我长期关注市场",
            "有一定基础，但不算专业",
            "不太有信心，主要跟着别人的建议",
        ],
        domain="finance",
        tags=["finance"],
    ),
    BootstrapQuestion(
        id="p2_domain_health",
        phase=2,
        type=QuestionType.FORCED_CHOICE,
        question="关于健康和生活方式的选择，你觉得自己的决策质量如何？",
        options=[
            "很好，我对健康知识了解较多",
            "还行，基本常识有但不深入",
            "不太好，经常不确定该怎么选",
        ],
        domain="health",
        tags=["health"],
    ),
    BootstrapQuestion(
        id="p2_domain_relationships",
        phase=2,
        type=QuestionType.FORCED_CHOICE,
        question="在人际关系和社交决策中，你觉得自己的判断力如何？",
        options=[
            "很强，我擅长读懂他人",
            "一般，有时候会判断失误",
            "较弱，经常不确定该如何应对",
        ],
        domain="relationships",
        tags=["relationships"],
    ),
    BootstrapQuestion(
        id="p2_domain_learning",
        phase=2,
        type=QuestionType.FORCED_CHOICE,
        question="在学习和技能发展的方向选择上，你觉得自己的决策如何？",
        options=[
            "很准确，我清楚知道该学什么",
            "还可以，但有时会走弯路",
            "经常迷茫，不太确定方向",
        ],
        domain="learning",
        tags=["learning"],
    ),
]

# ---------------------------------------------------------------------------
# Phase 3: Open-ended scenario questions — 3 questions
# ---------------------------------------------------------------------------

_PHASE3_QUESTIONS: List[BootstrapQuestion] = [
    BootstrapQuestion(
        id="p3_scenario_work",
        phase=3,
        type=QuestionType.OPEN_SCENARIO,
        question="请描述一个你最近做的重要工作决策。你当时面对哪些选项？最终为什么选了那个方向？回头看觉得怎么样？",
        tags=["work", "narrative"],
    ),
    BootstrapQuestion(
        id="p3_scenario_life",
        phase=3,
        type=QuestionType.OPEN_SCENARIO,
        question="回忆一个你在生活规划方面的关键选择（比如搬家、转行、开始或结束一段关系）。当时你是怎么想的？",
        tags=["life", "narrative"],
    ),
    BootstrapQuestion(
        id="p3_scenario_money",
        phase=3,
        type=QuestionType.OPEN_SCENARIO,
        question="描述一个涉及金钱的重大决定（比如一笔大额消费、投资、或者放弃一个赚钱机会）。你权衡了哪些因素？",
        tags=["finance", "narrative"],
    ),
]

# ---------------------------------------------------------------------------
# Assembled default question set
# ---------------------------------------------------------------------------

DEFAULT_QUESTIONS: List[BootstrapQuestion] = (
    _PHASE1_QUESTIONS + _PHASE2_QUESTIONS + _PHASE3_QUESTIONS
)
