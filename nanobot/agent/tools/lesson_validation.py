"""Validation rules for detailed lesson plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationIssue:
    rule: str
    severity: str
    message: str


@dataclass
class ValidationReport:
    passed: bool
    score: int
    issues: list[ValidationIssue] = field(default_factory=list)
    dimensions: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "dimensions": self.dimensions,
            "issues": [
                {"rule": x.rule, "severity": x.severity, "message": x.message}
                for x in self.issues
            ],
        }


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def validate_lesson_plan(
    plan: dict[str, Any],
    duration_minutes: int,
    objectives: list[str],
    needs_quiz: bool = False,
    needs_rubric: bool = False,
    needs_differentiation: bool = False,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    dimensions: dict[str, bool] = {}

    # 1. 结构完整性
    required_blocks = [
        "learning_objectives",
        "key_points",
        "teaching_process",
        "assessment",
        "board_outline",
    ]
    missing = [name for name in required_blocks if not plan.get(name)]
    dimensions["结构完整性"] = not missing
    if missing:
        issues.append(ValidationIssue("结构完整性", "high", f"缺少关键模块: {', '.join(missing)}"))

    # 2. 逻辑一致性（目标-活动-评价）
    process_text = " ".join(
        [
            f"{x.get('phase', '')} {x.get('teacher_activity', '')} {x.get('student_activity', '')} {x.get('design_intent', '')}"
            for x in plan.get("teaching_process", [])
            if isinstance(x, dict)
        ]
    )
    objective_alignment_ok = True
    for obj in objectives:
        token = obj.replace("学生能够", "").strip()[:8]
        if token and token not in process_text:
            objective_alignment_ok = False
            issues.append(ValidationIssue("目标活动对齐", "medium", f"目标可能未被教学流程充分覆盖: {obj}"))
            break

    dimensions["逻辑一致性"] = objective_alignment_ok

    # 3. 实施可行性（时长、资源、安全）
    total = 0
    for step in plan.get("teaching_process", []):
        if isinstance(step, dict):
            total += int(step.get("minutes", 0) or 0)

    time_ok = total == duration_minutes
    if not time_ok:
        issues.append(
            ValidationIssue(
                "时间分配合理性",
                "high",
                f"教学流程总时长 {total} 分钟，与课时 {duration_minutes} 分钟不一致",
            )
        )

    resources_ok = bool(plan.get("resources"))
    if not resources_ok:
        issues.append(ValidationIssue("资源明确性", "medium", "未提供明确教学资源/教具清单"))

    safety_ok = True
    topic_text = str(plan.get("topic", ""))
    if _contains_any(topic_text, ["实验", "化学", "体育", "户外"]):
        safety_notes = str(plan.get("safety_notes", ""))
        safety_ok = bool(safety_notes.strip())
        if not safety_ok:
            issues.append(ValidationIssue("安全性检查", "medium", "涉及实验/运动类主题，建议补充安全注意事项"))

    dimensions["实施可行性"] = time_ok and resources_ok and safety_ok

    # 4. 学生中心度
    student_actions = " ".join(
        [str(x.get("student_activity", "")) for x in plan.get("teaching_process", []) if isinstance(x, dict)]
    )
    student_centered = _contains_any(student_actions, ["讨论", "探究", "展示", "合作", "输出", "反思"])
    if not student_centered:
        issues.append(ValidationIssue("学生中心度", "medium", "学生活动偏弱，建议增加自主探究/协作输出环节"))

    has_diff = bool(plan.get("differentiation"))
    if needs_differentiation and not has_diff:
        issues.append(ValidationIssue("差异化教学", "high", "用户要求差异化作业/教学，但教案未体现分层设计"))

    dimensions["学生中心度"] = student_centered and (has_diff or not needs_differentiation)

    # 5. 活动设计深度
    questions_count = 0
    for step in plan.get("teaching_process", []):
        if isinstance(step, dict):
            questions = step.get("guiding_questions", [])
            if isinstance(questions, list):
                questions_count += len(questions)
    depth_ok = questions_count >= 3
    if not depth_ok:
        issues.append(ValidationIssue("活动设计深度", "medium", "教师引导问题少于3个，建议增加递进式问题链"))
    dimensions["活动设计深度"] = depth_ok

    # 6. 评价科学性
    assessment = plan.get("assessment", {}) if isinstance(plan.get("assessment"), dict) else {}
    has_formative = bool(assessment.get("formative"))
    has_summative = bool(assessment.get("summative"))
    has_rubric = bool(plan.get("assessment_rubric"))
    if needs_quiz and not _contains_any(str(assessment), ["测验", "quiz", "当堂检测"]):
        issues.append(ValidationIssue("评价科学性", "medium", "用户要求随堂测验，但评价设计中未体现"))
    if needs_rubric and not has_rubric:
        issues.append(ValidationIssue("评价科学性", "high", "用户要求评价量表（rubric），但教案未提供"))
    dimensions["评价科学性"] = has_formative and has_summative and (has_rubric or not needs_rubric)

    # 7. 语言与表述
    concrete_ok = True
    vague_hits = 0
    for step in plan.get("teaching_process", []):
        if not isinstance(step, dict):
            continue
        text = f"{step.get('teacher_activity', '')} {step.get('student_activity', '')}"
        if _contains_any(text, ["深入理解", "适当引导", "灵活处理"]):
            vague_hits += 1
    if vague_hits > 1:
        concrete_ok = False
        issues.append(ValidationIssue("语言与表述", "low", "存在较多泛化指令，建议改为可执行步骤和具体提问语"))
    dimensions["语言与表述"] = concrete_ok

    penalties = {"high": 20, "medium": 10, "low": 5}
    score = max(0, 100 - sum(penalties.get(x.severity, 5) for x in issues))
    passed = score >= 70 and all(dimensions.values())

    return ValidationReport(passed=passed, score=score, issues=issues, dimensions=dimensions)
