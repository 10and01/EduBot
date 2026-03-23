"""Teaching mode profiles and activity packs for advanced lesson generation."""

from __future__ import annotations

from typing import Any

TEACHING_MODE_PROFILES: dict[str, dict[str, Any]] = {
    "讲授型": {
        "core_concept": "高效传递系统知识，以教师为中心，目标是学生准确理解与记忆。",
        "time_ratio": {
            "导入": 0.05,
            "讲授新课": 0.70,
            "巩固练习": 0.20,
            "小结作业": 0.05,
        },
        "teacher_focus": "精讲串联，逻辑清晰，辅以板书、演示、提问。",
        "student_focus": "听讲、记笔记、回答即时性问题。",
        "evaluation_focus": "总结性评价为主，侧重知识复现与理解准确性。",
    },
    "探究发现式": {
        "core_concept": "经历知识生成过程，以学生为中心，培养科学思维与探究能力。",
        "time_ratio": {
            "创设情境/提出问题": 0.15,
            "猜想与假设": 0.15,
            "探索与验证": 0.50,
            "总结与应用": 0.20,
        },
        "teacher_focus": "设计有挑战性的主问题，提供资源支架并关键点拨。",
        "student_focus": "动手实验、观察记录、分析数据、归纳结论。",
        "evaluation_focus": "过程性评价为主，关注方案质量、操作规范、结论科学性。",
    },
    "小组合作式": {
        "core_concept": "通过社会互动建构知识，以互动为中心，培养协作与沟通能力。",
        "time_ratio": {
            "明确任务": 0.10,
            "小组合作学习": 0.60,
            "成果展示与交流": 0.20,
            "教师点评提升": 0.10,
        },
        "teacher_focus": "设计互赖任务，明确合作规则并巡视指导。",
        "student_focus": "组内分工、讨论辩论、共同制作成果。",
        "evaluation_focus": "混合评价，兼顾小组质量、个人贡献与同伴互评。",
    },
    "项目式": {
        "core_concept": "解决真实复杂问题，以成果为中心，培养综合实践与创新能力。",
        "time_ratio": {
            "入项与规划": 0.20,
            "知识与能力建构/探究": 0.30,
            "成果制作与修订": 0.40,
            "公开展示与反思": 0.10,
        },
        "teacher_focus": "设计驱动性问题，提供资源支持并管理项目进程。",
        "student_focus": "调研、规划、执行、迭代、展示与反思。",
        "evaluation_focus": "多元综合评价，关注最终产品与过程文档。",
    },
    "翻转课堂": {
        "core_concept": "知识传递前置，课堂用于内化与拓展，以个性化为中心。",
        "time_ratio": {
            "课前自主学习": 0.00,
            "快速检测": 0.10,
            "答疑与深化": 0.30,
            "协作探究与个性化应用": 0.50,
            "总结与前瞻": 0.10,
        },
        "teacher_focus": "组织高质量答疑与高阶任务，面向差异提供指导。",
        "student_focus": "课前完成资源学习，课中协作应用并输出成果。",
        "evaluation_focus": "形成性与表现性评价结合，关注迁移应用。",
    },
}

MODE_ACTIVITY_PACKS: dict[str, list[str]] = {
    "讲授型": ["精讲串联", "对比讲解", "层进式提问", "板书推演", "当堂检测"],
    "探究发现式": ["主问题链", "实验观察记录", "证据推理", "数据归纳", "迁移任务"],
    "小组合作式": ["角色分工", "小组辩论", "协作海报", "同伴互评", "成果汇报"],
    "项目式": ["驱动问题定义", "里程碑计划", "阶段复盘", "产品迭代", "公开展示"],
    "翻转课堂": ["课前微课单", "课前测验", "课堂答疑工单", "分层应用任务", "学习反思单"],
}

DEFAULT_TEACHING_MODE = "讲授型"


def normalize_mode(mode: str | None) -> str:
    if not mode:
        return DEFAULT_TEACHING_MODE
    mode = mode.strip()
    return mode if mode in TEACHING_MODE_PROFILES else DEFAULT_TEACHING_MODE


def get_mode_profile(mode: str | None) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    return TEACHING_MODE_PROFILES[normalized]


def get_mode_activity_pack(mode: str | None) -> list[str]:
    normalized = normalize_mode(mode)
    return MODE_ACTIVITY_PACKS.get(normalized, MODE_ACTIVITY_PACKS[DEFAULT_TEACHING_MODE])


def allocate_mode_minutes(mode: str | None, duration_minutes: int) -> list[dict[str, Any]]:
    profile = get_mode_profile(mode)
    ratio = profile["time_ratio"]
    phases = list(ratio.keys())
    if duration_minutes <= 0:
        duration_minutes = 40

    raw = [max(0, int(duration_minutes * float(ratio[p]))) for p in phases]
    consumed = sum(raw)
    remain = max(0, duration_minutes - consumed)
    idx = 0
    while remain > 0 and phases:
        raw[idx % len(raw)] += 1
        remain -= 1
        idx += 1

    allocations: list[dict[str, Any]] = []
    for i, phase in enumerate(phases):
        if phase == "课前自主学习" and raw[i] == 0:
            continue
        allocations.append({"phase": phase, "minutes": raw[i]})
    if not allocations:
        allocations = [{"phase": "教学活动", "minutes": duration_minutes}]
    return allocations
