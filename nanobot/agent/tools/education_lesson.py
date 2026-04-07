"""Lesson-plan and media generation tools for education-focused workflows."""

from __future__ import annotations

import json
from typing import Any

import httpx
import json_repair

from nanobot.agent.tools.teaching_modes import (
    allocate_mode_minutes,
    get_mode_activity_pack,
    get_mode_profile,
    normalize_mode,
)
from nanobot.agent.tools.base import Tool
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider


class LessonPlanGenerateTool(Tool):
    """Generate lesson plans in a fixed and predictable format."""

    def __init__(
        self,
        default_language: str = "zh",
        output_format: str = "markdown",
        include_citation: bool = True,
        detail_level: int = 2,
        llm_enhance: bool = True,
    ) -> None:
        self._default_language = default_language
        self._output_format = output_format
        self._include_citation = include_citation
        self._detail_level = max(1, min(3, int(detail_level)))
        self._llm_enhance = bool(llm_enhance)

    @property
    def name(self) -> str:
        return "lesson_plan_generate"

    @property
    def description(self) -> str:
        return "Generate a structured lesson plan with fixed sections for classroom design."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "grade": {"type": "string"},
                "topic": {"type": "string"},
                "duration_minutes": {"type": "integer", "minimum": 1, "maximum": 300},
                "teaching_objectives": {"type": "array", "items": {"type": "string"}},
                "prior_knowledge": {"type": "array", "items": {"type": "string"}},
                "learner_misconceptions": {"type": "array", "items": {"type": "string"}},
                "learner_interests": {"type": "array", "items": {"type": "string"}},
                "key_points": {"type": "array", "items": {"type": "string"}},
                "difficult_points": {"type": "array", "items": {"type": "string"}},
                "teaching_mode": {"type": "string"},
                "selected_activities": {"type": "array", "items": {"type": "string"}},
                "teacher_profile": {"type": "object"},
                "needs_quiz": {"type": "boolean"},
                "needs_rubric": {"type": "boolean"},
                "needs_differentiation": {"type": "boolean"},
                "detail_level": {"type": "integer", "minimum": 1, "maximum": 3},
                "llm_enhance": {"type": "boolean"},
                "include_handout": {"type": "boolean"},
                "include_answer_key": {"type": "boolean"},
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional retrieval evidence snippets or source lines",
                },
                "language": {"type": "string", "enum": ["zh", "en"]},
                "output_format": {"type": "string", "enum": ["markdown", "json"]},
            },
            "required": ["subject", "grade", "topic", "duration_minutes"],
        }

    async def execute(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration_minutes: int,
        teaching_objectives: list[str] | None = None,
        prior_knowledge: list[str] | None = None,
        learner_misconceptions: list[str] | None = None,
        learner_interests: list[str] | None = None,
        key_points: list[str] | None = None,
        difficult_points: list[str] | None = None,
        teaching_mode: str | None = None,
        selected_activities: list[str] | None = None,
        teacher_profile: dict[str, Any] | None = None,
        needs_quiz: bool = False,
        needs_rubric: bool = False,
        needs_differentiation: bool = False,
        detail_level: int | None = None,
        llm_enhance: bool | None = None,
        include_handout: bool = False,
        include_answer_key: bool = False,
        references: list[str] | None = None,
        language: str | None = None,
        output_format: str | None = None,
        **kwargs: Any,
    ) -> str:
        lang = language or self._default_language
        fmt = output_format or self._output_format
        detail = max(1, min(3, int(detail_level or self._detail_level)))
        enhance = self._llm_enhance if llm_enhance is None else bool(llm_enhance)
        objectives = teaching_objectives or [
            "理解核心概念并能复述关键定义" if lang == "zh" else "Understand and restate core concepts",
            "完成课堂任务并展示学习成果" if lang == "zh" else "Complete classroom activities and demonstrate outcomes",
            "通过评价反馈改进学习策略" if lang == "zh" else "Improve learning strategy through assessment feedback",
        ]
        mode = normalize_mode(teaching_mode)
        profile = get_mode_profile(mode)
        mode_allocations = allocate_mode_minutes(mode, duration_minutes)
        activities = selected_activities or get_mode_activity_pack(mode)[:3]

        inferred_key_points = key_points or [
            "核心概念理解与应用" if lang == "zh" else "Core concept understanding and application",
            "关键方法迁移与解释" if lang == "zh" else "Method transfer and explanation",
        ]
        inferred_difficult_points = difficult_points or [
            "抽象概念具体化" if lang == "zh" else "Concretize abstract concepts",
            "易错点纠偏" if lang == "zh" else "Correct common misconceptions",
        ]
        prior_knowledge = prior_knowledge or [
            "已掌握本课前置知识" if lang == "zh" else "Prerequisite knowledge has been introduced",
        ]
        learner_misconceptions = learner_misconceptions or [
            "容易记忆结论但忽略条件" if lang == "zh" else "Remembers conclusions but ignores constraints",
        ]
        learner_interests = learner_interests or [
            "对情境化任务和小组讨论更有兴趣" if lang == "zh" else "Shows stronger engagement in contextual and collaborative tasks",
        ]
        teacher_profile = teacher_profile or {}
        style_hint = str(teacher_profile.get("teaching_style", "")).strip()
        persona = teacher_profile.get("persona", {}) if isinstance(teacher_profile, dict) else {}
        basic_attrs = persona.get("basic_attributes", {}) if isinstance(persona, dict) else {}
        style_attrs = persona.get("teaching_style", {}) if isinstance(persona, dict) else {}
        prof_attrs = persona.get("professional_competence", {}) if isinstance(persona, dict) else {}
        implicit_attrs = persona.get("implicit_preferences", {}) if isinstance(persona, dict) else {}
        persona_summary = {
            "subject": str(basic_attrs.get("subject", "")).strip(),
            "grade_level": str(basic_attrs.get("grade_level", "")).strip(),
            "student_profile": str(basic_attrs.get("student_profile", "")).strip(),
            "class_atmosphere": str(basic_attrs.get("class_atmosphere", "")).strip(),
            "method_preference": str(style_attrs.get("method_preference", "")).strip() or style_hint,
            "interaction_pattern": str(style_attrs.get("interaction_pattern", "")).strip(),
            "assessment_preference": str(style_attrs.get("assessment_preference", "")).strip(),
            "experience_level": str(prof_attrs.get("experience_level", "")).strip(),
            "development_goals": prof_attrs.get("development_goals", []) if isinstance(prof_attrs.get("development_goals", []), list) else [],
            "education_philosophy": str(implicit_attrs.get("education_philosophy", "")).strip(),
            "good_lesson_definition": str(implicit_attrs.get("good_lesson_definition", "")).strip(),
            "personal_interests": implicit_attrs.get("personal_interests", []) if isinstance(implicit_attrs.get("personal_interests", []), list) else [],
        }

        professional_prompt = self._build_professional_prompt(
            lang=lang,
            subject=subject,
            grade=grade,
            topic=topic,
            duration_minutes=duration_minutes,
            mode=mode,
            objectives=objectives,
            prior_knowledge=prior_knowledge,
            misconceptions=learner_misconceptions,
            interests=learner_interests,
            key_points=inferred_key_points,
            difficult_points=inferred_difficult_points,
            selected_activities=activities,
            teacher_style=style_hint,
            teacher_persona=persona_summary,
            needs_quiz=needs_quiz,
            needs_rubric=needs_rubric,
            needs_differentiation=needs_differentiation,
        )

        is_zh = lang == "zh"
        knowledge_breakdown = [
            {
                "name": "核心定义" if is_zh else "Core Definition",
                "explain": (
                    "先给出定义和反例，帮助学生区分概念边界。"
                    if is_zh else
                    "Start from definition and non-examples to clarify boundaries."
                ),
                "examples": (
                    [f"正例：与“{topic}”紧密相关的典型情境", f"反例：看似相关但不满足关键条件的情境"]
                    if is_zh else
                    [f"Example: a typical scenario aligned with '{topic}'", "Non-example: similar-looking but violates a key condition"]
                ),
            },
            {
                "name": "关键方法" if is_zh else "Key Method",
                "explain": (
                    "步骤化讲解并说明每一步为什么成立。"
                    if is_zh else
                    "Explain each step and why it works."
                ),
                "examples": (
                    [f"示范：围绕“{topic}”的基础题（带步骤）", f"变式：改变条件/数据，比较解法差异"]
                    if is_zh else
                    [f"Guided: a core task on '{topic}' with steps", "Variant: change constraints/data and compare methods"]
                ),
            },
            {
                "name": "迁移应用" if is_zh else "Transfer",
                "explain": (
                    "将知识点放入真实情境，训练迁移能力。"
                    if is_zh else
                    "Apply the concept to real contexts."
                ),
                "examples": (
                    [f"生活应用：用“{topic}”解释/解决一个身边问题", "跨学科：把方法迁移到另一学科或新领域"]
                    if is_zh else
                    [f"Real-world: solve a daily-life problem using '{topic}'", "Cross-disciplinary: transfer to another subject"]
                ),
            },
        ]
        misconceptions = [
            {
                "misconception": item,
                "correction": (
                    "通过反例、追问和同伴互评进行纠偏"
                    if is_zh else
                    "Address with counterexamples, probing questions, and peer feedback"
                ),
            }
            for item in learner_misconceptions
        ]
        teaching_script = [
            {
                "phase": "导入" if is_zh else "Warm-up",
                "teacher_script": (
                    "请先观察这个情境，想一想它和上节课知识有什么联系。"
                    if is_zh else
                    "Observe this context and connect it to prior learning."
                ),
            },
            {
                "phase": "新授" if is_zh else "Instruction",
                "teacher_script": (
                    "我们把内容拆成三个步骤：识别条件、选择方法、验证结果。"
                    if is_zh else
                    "We will break this into three moves: identify constraints, pick method, verify."
                ),
            },
            {
                "phase": "实践" if is_zh else "Practice",
                "teacher_script": (
                    "请小组完成任务并说明每一步依据。"
                    if is_zh else
                    "Work in teams and justify each step of your solution."
                ),
            },
            {
                "phase": "总结与评价" if is_zh else "Wrap-up & Assessment",
                "teacher_script": (
                    "请写下今天最有把握和最困惑的一个点。"
                    if is_zh else
                    "Write one thing you mastered and one thing still unclear."
                ),
            },
        ]
        differentiation = {
            "basic": "完成基础题并复述概念" if is_zh else "Complete core tasks and restate concepts",
            "proficient": "完成变式题并比较解法" if is_zh else "Solve variants and compare methods",
            "advanced": "设计真实情境并完整求解" if is_zh else "Design and solve an authentic scenario",
        }
        assessment_rubric = [
            {
                "criterion": "概念理解" if is_zh else "Conceptual Understanding",
                "excellent": "准确并能举例" if is_zh else "Accurate with examples",
                "good": "基本准确" if is_zh else "Mostly accurate",
                "needs_improvement": "表述模糊" if is_zh else "Ambiguous understanding",
            },
            {
                "criterion": "方法应用" if is_zh else "Method Application",
                "excellent": "步骤清晰且可迁移" if is_zh else "Clear and transferable steps",
                "good": "可完成常规题" if is_zh else "Can solve routine tasks",
                "needs_improvement": "步骤不完整" if is_zh else "Incomplete steps",
            },
            {
                "criterion": "表达反思" if is_zh else "Reflection and Explanation",
                "excellent": "解释有逻辑并有反思" if is_zh else "Logical explanation with reflection",
                "good": "能解释但不深入" if is_zh else "Basic explanation",
                "needs_improvement": "难以解释" if is_zh else "Cannot justify reasoning",
            },
        ]
        board_outline = [
            "左区：学习目标与达成标准" if is_zh else "Left: goals and success criteria",
            "中区：核心概念与步骤图" if is_zh else "Middle: concept map and method steps",
            "右区：典型例题与误区提醒" if is_zh else "Right: worked examples and misconceptions",
            "下区：课堂小结与作业" if is_zh else "Bottom: summary and homework",
        ]

        process_blocks = self._build_teaching_process(
            lang=lang,
            mode=mode,
            allocations=mode_allocations,
            key_points=inferred_key_points,
            difficult_points=inferred_difficult_points,
            activities=activities,
            needs_quiz=needs_quiz,
            detail_level=detail,
        )

        resolved_references = [str(x).strip() for x in (references or []) if str(x).strip()]
        if not resolved_references:
            resolved_references = await self._auto_retrieve_references(
                subject=subject,
                grade=grade,
                topic=topic,
                detail_level=detail,
            )

        in_class_quiz = []
        if needs_quiz or detail >= 3:
            in_class_quiz = self._build_default_quiz(lang=lang, topic=topic, key_points=inferred_key_points)

        worksheet = None
        if include_handout or detail >= 3:
            worksheet = self._build_default_worksheet(
                lang=lang,
                subject=subject,
                grade=grade,
                topic=topic,
                key_points=inferred_key_points,
                difficult_points=inferred_difficult_points,
                include_answer_key=include_answer_key,
            )

        plan = {
            "subject": subject,
            "grade": grade,
            "topic": topic,
            "duration_minutes": duration_minutes,
            "teaching_mode": mode,
            "mode_profile": profile,
            "teacher_style_hint": style_hint,
            "generation_prompt": professional_prompt,
            "selected_activities": activities,
            "detail_level": detail,
            "learning_objectives": objectives,
            "knowledge_breakdown": knowledge_breakdown,
            "learner_analysis": self._render_learner_analysis(
                lang=lang,
                prior_knowledge=prior_knowledge,
                misconceptions=learner_misconceptions,
                interests=learner_interests,
            ),
            "prior_knowledge": prior_knowledge,
            "learner_interests": learner_interests,
            "key_points": inferred_key_points,
            "difficult_points": inferred_difficult_points,
            "misconceptions": misconceptions,
            "teaching_script": teaching_script,
            "differentiation": differentiation,
            "teaching_process": process_blocks,
            "in_class_quiz": in_class_quiz,
            "worksheet": worksheet,
            "assessment": {
                "formative": (
                    "课堂追问、同伴互评、任务观察单"
                    if lang == "zh" else
                    "Probing questions, peer review, and task observation checklist"
                ),
                "summative": (
                    "课后作业与阶段测评"
                    if lang == "zh" else
                    "Homework and stage-based assessment"
                ),
                "needs_quiz": needs_quiz,
                "needs_rubric": needs_rubric,
            },
            "assessment_rubric": assessment_rubric if (needs_rubric or detail >= 2) else assessment_rubric[:2],
            "homework": "分层作业：基础巩固 + 拓展挑战" if lang == "zh" else "Tiered homework: core practice + extension challenge",
            "board_plan": "标题-要点-示例-总结四区布局" if lang == "zh" else "Four-zone board layout: title, key points, examples, summary",
            "board_outline": board_outline,
            "safety_notes": (
                "若涉及实验操作，教师先演示并提醒佩戴护具。"
                if is_zh else
                "For experiments, teacher demonstration and safety equipment reminders are mandatory."
            ),
            "resources": [
                "课件/板书模板" if lang == "zh" else "Slides/board template",
                "练习单与评价量规" if lang == "zh" else "Worksheet and assessment rubric",
            ],
        }

        if enhance and detail >= 2:
            enhanced = await self._llm_enhance_plan(
                lang=lang,
                base_plan=plan,
                subject=subject,
                grade=grade,
                topic=topic,
                duration_minutes=duration_minutes,
                mode=mode,
                objectives=objectives,
                prior_knowledge=prior_knowledge,
                misconceptions=learner_misconceptions,
                interests=learner_interests,
                key_points=inferred_key_points,
                difficult_points=inferred_difficult_points,
                activities=activities,
                needs_quiz=needs_quiz,
                include_handout=include_handout,
                include_answer_key=include_answer_key,
                detail_level=detail,
                references=resolved_references,
            )
            if enhanced:
                plan = self._merge_plan(plan, enhanced)

        if self._include_citation and resolved_references:
            plan["references"] = resolved_references

        markdown = self._render_markdown(plan=plan, lang=lang)

        if fmt == "json":
            return json.dumps(
                {
                    "status": "ok",
                    "lesson_plan": plan,
                    "lesson_markdown": markdown,
                    "generation_prompt": professional_prompt,
                },
                ensure_ascii=False,
            )

        return markdown

    def _render_learner_analysis(
        self,
        lang: str,
        prior_knowledge: list[str],
        misconceptions: list[str],
        interests: list[str],
    ) -> str:
        if lang != "zh":
            return (
                f"Prerequisite knowledge: {'; '.join(prior_knowledge)}. "
                f"Common misconceptions: {'; '.join(misconceptions)}. "
                f"Interests: {'; '.join(interests)}."
            )
        return (
            f"已有基础：{'；'.join(prior_knowledge)}。"
            f"常见误区：{'；'.join(misconceptions)}。"
            f"兴趣点：{'；'.join(interests)}。"
        )

    def _build_professional_prompt(
        self,
        *,
        lang: str,
        subject: str,
        grade: str,
        topic: str,
        duration_minutes: int,
        mode: str,
        objectives: list[str],
        prior_knowledge: list[str],
        misconceptions: list[str],
        interests: list[str],
        key_points: list[str],
        difficult_points: list[str],
        selected_activities: list[str],
        teacher_style: str,
        teacher_persona: dict[str, Any],
        needs_quiz: bool,
        needs_rubric: bool,
        needs_differentiation: bool,
    ) -> str:
        persona_lines = []
        for key, value in teacher_persona.items():
            if isinstance(value, list):
                if value:
                    persona_lines.append(f"{key}={'、'.join(str(x) for x in value)}")
            elif str(value).strip():
                persona_lines.append(f"{key}={value}")
        persona_text = "；".join(persona_lines) if persona_lines else "未提供"

        if lang != "zh":
            return (
                f"You are an expert {subject} curriculum specialist. Generate a detailed, classroom-ready lesson plan for {grade}. "
                f"Topic: {topic}; Duration: {duration_minutes} minutes; Teaching mode: {mode}. "
                f"Objectives: {' | '.join(objectives)}. Prior knowledge: {' | '.join(prior_knowledge)}. "
                f"Misconceptions: {' | '.join(misconceptions)}. Interests: {' | '.join(interests)}. "
                f"Key points: {' | '.join(key_points)}. Difficult points: {' | '.join(difficult_points)}. "
                f"Prioritize activities: {' | '.join(selected_activities)}. Teacher style preference: {teacher_style or 'N/A'}. "
                f"Teacher persona profile: {persona_text}. "
                "The process must include precise time allocation, teacher prompts, at least 3 progressive questions, "
                "student outputs, instructional intent, differentiated support, board plan, and homework."
            )

        evaluation_requirements = []
        if needs_quiz:
            evaluation_requirements.append("设计随堂测验题")
        if needs_rubric:
            evaluation_requirements.append("提供小组合作评价量表")
        if needs_differentiation:
            evaluation_requirements.append("提供差异化作业（必做+选做）")
        eval_text = "；".join(evaluation_requirements) if evaluation_requirements else "保持形成性与总结性评价平衡"

        return (
            f"你是一位经验丰富的{subject}教研员。请基于以下信息，生成一份可直接用于课堂的详细教案。\n"
            f"核心指令：教案需严格遵循【{mode}】核心理念，突出【{'、'.join(selected_activities)}】活动，"
            f"并自然融入对学情的应对策略。\n"
            f"具体信息：课题={topic}；学段/年级={grade}；课时={duration_minutes}分钟；"
            f"教师风格偏好={teacher_style or '未指定'}。\n"
            f"教师画像摘要：{persona_text}。\n"
            f"目标（学生能够）：{'；'.join(objectives)}。请扩展为可观测的三维目标。\n"
            f"学情：已有基础={'；'.join(prior_knowledge)}；常见误区={'；'.join(misconceptions)}；兴趣点={'；'.join(interests)}。\n"
            f"重难点：重点={'；'.join(key_points)}；难点={'；'.join(difficult_points)}。\n"
            f"评估要求：{eval_text}。\n"
            "生成要求：\n"
            "1) 教学过程必须提供精确时间分配（例如 导入-5分钟）。\n"
            "2) 每个环节需提供教师活动、学生活动、设计意图。\n"
            "3) 教师活动中必须包含至少3个递进式问题。\n"
            "4) 学生活动需明确可观察行为和产出。\n"
            "5) 必须给出差异化支持策略（基础/进阶/拓展）。\n"
            "6) 给出板书设计草图与课后作业。\n"
            "请以专业教案格式输出，语言严谨，步骤清晰。"
        )

    def _build_teaching_process(
        self,
        *,
        lang: str,
        mode: str,
        allocations: list[dict[str, Any]],
        key_points: list[str],
        difficult_points: list[str],
        activities: list[str],
        needs_quiz: bool,
        detail_level: int = 2,
    ) -> list[dict[str, Any]]:
        process: list[dict[str, Any]] = []
        for i, item in enumerate(allocations):
            phase = str(item.get("phase", "教学活动"))
            minutes = int(item.get("minutes", 0) or 0)
            focus = key_points[min(i, len(key_points) - 1)] if key_points else "核心知识"
            challenge = difficult_points[min(i, len(difficult_points) - 1)] if difficult_points else "难点突破"
            activity = activities[min(i, len(activities) - 1)] if activities else "课堂活动"

            if lang == "zh":
                guiding_questions = [
                    f"问题1：本环节与{focus}有什么直接关系？",
                    f"问题2：如果忽略关键条件，会出现什么错误？",
                    f"问题3：如何把{focus}迁移到一个新情境中？",
                ]
                student_output = f"完成{activity}任务单，并口头解释{focus}。"
                teacher_activity = f"围绕“{focus}”组织{activity}，通过追问突破“{challenge}”。"
                design_intent = f"服务于目标达成，并针对学情中的误区进行纠偏。"
                if needs_quiz and i == len(allocations) - 1:
                    teacher_activity += " 设计3-5道当堂测验题进行即时诊断。"
            else:
                guiding_questions = [
                    f"Q1: How does this phase connect to {focus}?",
                    "Q2: What error appears when a key condition is ignored?",
                    "Q3: How can this method transfer to a new context?",
                ]
                student_output = f"Complete the {activity} task sheet and explain reasoning."
                teacher_activity = f"Lead {activity} around {focus} and address {challenge}."
                design_intent = "Align activity with goals and fix likely misconceptions."

            block: dict[str, Any] = {
                "phase": phase,
                "minutes": minutes,
                "teacher_activity": teacher_activity,
                "student_activity": student_output,
                "design_intent": design_intent,
                "guiding_questions": guiding_questions,
                "student_output": student_output,
                "mode": mode,
                "activity": activity,
            }
            if detail_level >= 2:
                if lang == "zh":
                    block.update({
                        "materials": ["投影/板书", "任务单/练习单", "计时器"],
                        "check_for_understanding": ["随机抽答", "同伴互评", "教师巡回观察"],
                        "success_criteria": [
                            "能说出关键概念/条件",
                            "能按步骤完成任务并解释依据",
                        ],
                        "common_errors": [
                            "只记结论不说条件",
                            "步骤跳跃导致推理断裂",
                        ],
                    })
                else:
                    block.update({
                        "materials": ["Slides/board", "Task sheet", "Timer"],
                        "check_for_understanding": ["Cold call", "Peer review", "Teacher circulation"],
                        "success_criteria": ["State key conditions", "Complete task with justified steps"],
                        "common_errors": ["States conclusion without constraints", "Skips steps in reasoning"],
                    })
            process.append(block)
        return process

    def _build_default_quiz(self, *, lang: str, topic: str, key_points: list[str]) -> list[dict[str, Any]]:
        kp = key_points[0] if key_points else (topic or "")
        if lang == "zh":
            return [
                {
                    "type": "单选",
                    "question": f"下列哪一项最能体现“{kp}”的关键条件？",
                    "answer": "选项B（示例）",
                    "explanation": "关键在于条件是否满足；不满足则结论不成立。",
                    "difficulty": "基础",
                },
                {
                    "type": "填空",
                    "question": f"把“{kp}”应用到新情境时，第一步应先______。",
                    "answer": "识别条件/已知量（示例）",
                    "explanation": "先定条件再选方法，避免套公式。",
                    "difficulty": "中等",
                },
                {
                    "type": "简答",
                    "question": f"请用1-2句话解释：为什么忽略某个关键条件会导致错误？（结合“{topic}”）",
                    "answer": "答案要点：指出条件作用 + 给出反例或错误结果（示例）。",
                    "explanation": "检验是否真正理解边界与适用范围。",
                    "difficulty": "提升",
                },
            ]
        return [
            {
                "type": "MCQ",
                "question": f"Which option best reflects a key condition of '{kp}'?",
                "answer": "Option B (example)",
                "explanation": "The conclusion holds only when conditions are met.",
                "difficulty": "Easy",
            },
            {
                "type": "Fill-in",
                "question": f"When transferring '{kp}' to a new context, the first step is to _____.",
                "answer": "Identify constraints/givens (example)",
                "explanation": "Conditions first, method second.",
                "difficulty": "Medium",
            },
            {
                "type": "Short answer",
                "question": f"In 1–2 sentences, explain why ignoring a key condition causes errors (use '{topic}').",
                "answer": "Key points: role of condition + counterexample/incorrect outcome (example).",
                "explanation": "Checks boundary understanding and reasoning.",
                "difficulty": "Hard",
            },
        ]

    def _build_default_worksheet(
        self,
        *,
        lang: str,
        subject: str,
        grade: str,
        topic: str,
        key_points: list[str],
        difficult_points: list[str],
        include_answer_key: bool,
    ) -> dict[str, Any]:
        if lang == "zh":
            sheet: dict[str, Any] = {
                "title": f"{subject}学习单：{topic}",
                "grade": grade,
                "sections": [
                    {
                        "name": "概念速记",
                        "items": [
                            f"用一句话写出本课核心概念（围绕：{'、'.join(key_points[:2]) or topic}）。",
                            "写出一个正例和一个反例，并说明理由。",
                        ],
                    },
                    {
                        "name": "方法步骤",
                        "items": [
                            "把解决问题的步骤写成 1-2-3 列表，并标注每步依据。",
                            f"针对难点（{'、'.join(difficult_points[:2]) or '本课难点'}）写出你的提醒语。",
                        ],
                    },
                    {
                        "name": "迁移练习",
                        "items": [
                            "给出一个生活情境问题，说明如何用本课方法解决。",
                            "把题目条件改一改，预测会出现的错误并纠正。",
                        ],
                    },
                    {
                        "name": "退出卡",
                        "items": [
                            "我今天最有把握的一点是：______",
                            "我今天仍困惑的一点是：______（我需要的帮助：______）",
                        ],
                    },
                ],
            }
            if include_answer_key:
                sheet["answer_key"] = [
                    "答案要点示例：概念=定义+边界；正反例=条件是否满足；步骤=先条件后方法；迁移=新情境建模+验证。",
                ]
            return sheet

        sheet = {
            "title": f"{subject} Worksheet: {topic}",
            "grade": grade,
            "sections": [
                {
                    "name": "Concept Check",
                    "items": [
                        f"Define the core concept (focus: {', '.join(key_points[:2]) or topic}).",
                        "Provide one example and one non-example with justification.",
                    ],
                },
                {
                    "name": "Method Steps",
                    "items": [
                        "Write the solution steps as 1-2-3 and justify each step.",
                        f"Write a reminder sentence for the challenge ({', '.join(difficult_points[:2]) or 'today’s challenge'}).",
                    ],
                },
                {
                    "name": "Transfer",
                    "items": [
                        "Create a real-life scenario and explain how to solve it using today’s method.",
                        "Modify a condition, predict a likely error, and correct it.",
                    ],
                },
                {
                    "name": "Exit Ticket",
                    "items": [
                        "One thing I’m confident about: ____",
                        "One thing I’m still unsure about: ____ (help I need: ____)",
                    ],
                },
            ],
        }
        if include_answer_key:
            sheet["answer_key"] = [
                "Example key points: definition + boundary; example vs non-example; constraints-first workflow; transfer by modeling + verification.",
            ]
        return sheet

    async def _auto_retrieve_references(
        self,
        *,
        subject: str,
        grade: str,
        topic: str,
        detail_level: int,
    ) -> list[str]:
        try:
            cfg = load_config()
            if not getattr(cfg, "education", None) or not cfg.education.enabled:
                return []
            workspace = cfg.workspace_path.resolve()
            vectordb_rel = str(cfg.education.vectors.path)
            collection_name = str(cfg.education.vectors.collection)
            top_k = int(cfg.education.vectors.top_k)
            if detail_level >= 3:
                top_k = max(top_k, 8)
            top_k = max(1, min(20, top_k))

            if getattr(cfg.education, "auto_import_materials", True):
                materials_dir = str(getattr(cfg.education, "materials_dir", "documents/materials") or "").strip()
                if materials_dir:
                    try:
                        from pathlib import Path

                        from nanobot.agent.tools.education_document import DocumentImportDirTool

                        p = Path(materials_dir).expanduser()
                        if not p.is_absolute():
                            (workspace / p).resolve().mkdir(parents=True, exist_ok=True)

                        importer = DocumentImportDirTool(
                            workspace=workspace,
                            vectordb_path=vectordb_rel,
                            collection_name=collection_name,
                        )
                        await importer.execute(
                            path=materials_dir,
                            recursive=True,
                            max_files=200,
                            subject=subject,
                            grade=grade,
                        )
                    except Exception:
                        pass

            vectordb_path = (workspace / vectordb_rel).resolve()
            try:
                import chromadb
            except Exception:
                return []
            vectordb_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(vectordb_path))
            collection = client.get_or_create_collection(name=collection_name)

            where: dict[str, Any] = {}
            if subject.strip():
                where["subject"] = subject.strip()
            if grade.strip():
                where["grade"] = grade.strip()

            query = f"{topic} 教案 教学设计 重点 难点 活动"
            result = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            dists = result.get("distances", [[]])[0]
            refs: list[str] = []
            for doc, meta, dist in zip(docs, metas, dists, strict=False):
                if not doc:
                    continue
                m = meta or {}
                src = str(m.get("source_path", "")).strip()
                score = round(1.0 - float(dist), 4) if dist is not None else None
                snippet = str(doc).strip().replace("\n", " ")
                snippet = snippet[:900]
                prefix = f"[{src} | score={score}]" if src else f"[score={score}]"
                refs.append(f"{prefix} {snippet}")
            return refs
        except Exception:
            return []

    async def _llm_enhance_plan(
        self,
        *,
        lang: str,
        base_plan: dict[str, Any],
        subject: str,
        grade: str,
        topic: str,
        duration_minutes: int,
        mode: str,
        objectives: list[str],
        prior_knowledge: list[str],
        misconceptions: list[str],
        interests: list[str],
        key_points: list[str],
        difficult_points: list[str],
        activities: list[str],
        needs_quiz: bool,
        include_handout: bool,
        include_answer_key: bool,
        detail_level: int,
        references: list[str],
    ) -> dict[str, Any] | None:
        config = load_config()
        model = config.agents.defaults.model
        api_key = config.get_api_key(model)
        if not api_key:
            return None
        provider_cfg = config.get_provider(model)
        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=(provider_cfg.extra_headers if provider_cfg else None),
            provider_name=config.get_provider_name(model),
        )

        if lang == "zh":
            system = "你是一位资深教研员与一线教师共同体。只输出严格JSON，不要代码块，不要额外解释。"
            ref_lines = [str(x).strip()[:900] for x in references if str(x).strip()][:10]
            refs_block = ""
            if ref_lines:
                refs_block = "参考资料（请优先借鉴/引用，禁止编造来源）：\n" + "\n".join(f"- {x}" for x in ref_lines) + "\n"
            user = (
                "请基于以下信息，把教案改写得更细致、可直接上课，并尽量具体到课堂用语/提问/预期学生回答。\n"
                f"学科={subject}\n年级={grade}\n课题={topic}\n时长={duration_minutes}分钟\n教学模式={mode}\n"
                f"学习目标={'；'.join(objectives)}\n"
                f"学情：已有基础={'；'.join(prior_knowledge)}；误区={'；'.join(misconceptions)}；兴趣点={'；'.join(interests)}\n"
                f"重难点：重点={'；'.join(key_points)}；难点={'；'.join(difficult_points)}\n"
                f"活动优先：{'、'.join(activities)}\n"
                f"{refs_block}"
                "输出JSON结构（缺少的字段也要给空值）：\n"
                "{\n"
                '  "knowledge_breakdown": [{"name": "...", "explain": "...", "examples": ["..."]}],\n'
                '  "teaching_process": [{"phase": "...", "minutes": 0, "teacher_activity": "...", "student_activity": "...", "design_intent": "...", "guiding_questions": ["..."], "materials": ["..."], "check_for_understanding": ["..."], "success_criteria": ["..."], "common_errors": ["..."]}],\n'
                '  "teaching_script": [{"phase": "...", "teacher_script": "...", "expected_student_response": "...", "key_questions": ["..."]}],\n'
                '  "in_class_quiz": [{"type": "...", "question": "...", "answer": "...", "explanation": "...", "difficulty": "..."}],\n'
                '  "worksheet": {"title": "...", "grade": "...", "sections": [{"name": "...", "items": ["..."]}], "answer_key": ["..."]}\n'
                "}\n"
                f"细致程度：{detail_level}(1简要/2详细/3非常详细)。"
                f"随堂测验需要：{str(needs_quiz or detail_level >= 3)}；学习单需要：{str(include_handout or detail_level >= 3)}；答案要点需要：{str(include_answer_key)}。"
            )
        else:
            system = "You are a senior curriculum specialist. Output strict JSON only. No code fences, no extra text."
            ref_lines = [str(x).strip()[:900] for x in references if str(x).strip()][:10]
            refs_block = ""
            if ref_lines:
                refs_block = "Reference materials (prioritize and do not fabricate sources):\n" + "\n".join(f"- {x}" for x in ref_lines) + "\n"
            user = (
                "Rewrite the lesson plan to be classroom-ready with concrete teacher prompts, questions, and expected student responses.\n"
                f"Subject={subject}\nGrade={grade}\nTopic={topic}\nDuration={duration_minutes}\nTeachingMode={mode}\n"
                f"Objectives={' | '.join(objectives)}\n"
                f"PriorKnowledge={' | '.join(prior_knowledge)}\nMisconceptions={' | '.join(misconceptions)}\nInterests={' | '.join(interests)}\n"
                f"KeyPoints={' | '.join(key_points)}\nChallenges={' | '.join(difficult_points)}\n"
                f"PriorityActivities={' | '.join(activities)}\n"
                f"{refs_block}"
                "Output JSON with this shape:\n"
                "{\n"
                '  "knowledge_breakdown": [{"name": "...", "explain": "...", "examples": ["..."]}],\n'
                '  "teaching_process": [{"phase": "...", "minutes": 0, "teacher_activity": "...", "student_activity": "...", "design_intent": "...", "guiding_questions": ["..."], "materials": ["..."], "check_for_understanding": ["..."], "success_criteria": ["..."], "common_errors": ["..."]}],\n'
                '  "teaching_script": [{"phase": "...", "teacher_script": "...", "expected_student_response": "...", "key_questions": ["..."]}],\n'
                '  "in_class_quiz": [{"type": "...", "question": "...", "answer": "...", "explanation": "...", "difficulty": "..."}],\n'
                '  "worksheet": {"title": "...", "grade": "...", "sections": [{"name": "...", "items": ["..."]}], "answer_key": ["..."]}\n'
                "}\n"
                f"Detail level: {detail_level} (1 basic, 2 detailed, 3 very detailed). "
                f"Quiz needed: {str(needs_quiz or detail_level >= 3)}; Worksheet needed: {str(include_handout or detail_level >= 3)}; Answer key: {str(include_answer_key)}."
            )

        try:
            resp = await provider.chat(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=None,
                model=model,
                max_tokens=4096 if detail_level >= 3 else 3072,
                temperature=0.2 if detail_level >= 3 else 0.1,
                tool_choice="none",
            )
            content = (resp.content or "").strip()
            if not content:
                return None
            data = json_repair.loads(content)
            if isinstance(data, dict):
                return data
            return None
        except Exception:
            return None

    @staticmethod
    def _merge_plan(base: dict[str, Any], enhanced: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key in ("knowledge_breakdown", "teaching_process", "teaching_script", "in_class_quiz", "worksheet"):
            val = enhanced.get(key)
            if val is None:
                continue
            merged[key] = val
        return merged

    def _render_markdown(self, plan: dict[str, Any], lang: str) -> str:
        topic = str(plan.get("topic", ""))
        subject = str(plan.get("subject", ""))
        grade = str(plan.get("grade", ""))
        duration_minutes = int(plan.get("duration_minutes", 0) or 0)

        lines = [
            f"# 教案：{topic}" if lang == "zh" else f"# Lesson Plan: {topic}",
            "",
            f"- 学科：{subject}" if lang == "zh" else f"- Subject: {subject}",
            f"- 年级：{grade}" if lang == "zh" else f"- Grade: {grade}",
            f"- 时长：{duration_minutes} 分钟" if lang == "zh" else f"- Duration: {duration_minutes} minutes",
            f"- 教学模式：{plan.get('teaching_mode', '')}" if lang == "zh" else f"- Teaching Mode: {plan.get('teaching_mode', '')}",
            "",
            "## 学习目标" if lang == "zh" else "## Learning Objectives",
        ]
        for idx, item in enumerate(plan.get("learning_objectives", []), start=1):
            lines.append(f"{idx}. {item}")

        lines.extend([
            "",
            "## 学情分析" if lang == "zh" else "## Learner Analysis",
            str(plan.get("learner_analysis", "")),
            "",
            "## 知识点拆解与讲解策略" if lang == "zh" else "## Knowledge Breakdown and Teaching Strategy",
        ])
        for item in plan.get("knowledge_breakdown", []):
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('name', '')}：{item.get('explain', '')}" if lang == "zh" else f"- {item.get('name', '')}: {item.get('explain', '')}")
            for example in item.get("examples", []):
                lines.append(f"  - {example}")

        lines.extend([
            "",
            "## 教学重点与难点" if lang == "zh" else "## Key Points and Challenges",
        ])
        for item in plan.get("key_points", []):
            lines.append(f"- 重点：{item}" if lang == "zh" else f"- Key Point: {item}")
        for item in plan.get("difficult_points", []):
            lines.append(f"- 难点：{item}" if lang == "zh" else f"- Challenge: {item}")

        lines.extend(["", "## 常见误区与纠偏" if lang == "zh" else "## Misconceptions and Corrections"])
        for item in plan.get("misconceptions", []):
            if not isinstance(item, dict):
                continue
            if lang == "zh":
                lines.append(f"- 误区：{item.get('misconception', '')}")
                lines.append(f"  - 纠偏：{item.get('correction', '')}")
            else:
                lines.append(f"- Misconception: {item.get('misconception', '')}")
                lines.append(f"  - Correction: {item.get('correction', '')}")

        lines.extend(["", "## 教学流程" if lang == "zh" else "## Teaching Process"])
        for step in plan.get("teaching_process", []):
            if not isinstance(step, dict):
                continue
            lines.extend([
                f"### {step.get('phase', '')}（{step.get('minutes', 0)} 分钟）" if lang == "zh" else f"### {step.get('phase', '')} ({step.get('minutes', 0)} min)",
                f"- 教师活动：{step.get('teacher_activity', '')}" if lang == "zh" else f"- Teacher: {step.get('teacher_activity', '')}",
                f"- 学生活动：{step.get('student_activity', '')}" if lang == "zh" else f"- Students: {step.get('student_activity', '')}",
                f"- 设计意图：{step.get('design_intent', '')}" if lang == "zh" else f"- Instructional Intent: {step.get('design_intent', '')}",
            ])
            if step.get("guiding_questions"):
                lines.append("- 递进式问题：" if lang == "zh" else "- Progressive Questions:")
                for q in step.get("guiding_questions", []):
                    lines.append(f"  - {q}")
            if step.get("materials"):
                lines.append("- 物料/教具：" if lang == "zh" else "- Materials:")
                for m in step.get("materials", []):
                    lines.append(f"  - {m}")
            if step.get("check_for_understanding"):
                lines.append("- 过程性检查：" if lang == "zh" else "- Checks for Understanding:")
                for c in step.get("check_for_understanding", []):
                    lines.append(f"  - {c}")
            if step.get("success_criteria"):
                lines.append("- 达成标准：" if lang == "zh" else "- Success Criteria:")
                for s in step.get("success_criteria", []):
                    lines.append(f"  - {s}")
            if step.get("common_errors"):
                lines.append("- 易错点提醒：" if lang == "zh" else "- Common Errors:")
                for e in step.get("common_errors", []):
                    lines.append(f"  - {e}")

        lines.extend(["", "## 课堂讲解脚本" if lang == "zh" else "## Classroom Script"])
        for item in plan.get("teaching_script", []):
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('phase', '')}：{item.get('teacher_script', '')}" if lang == "zh" else f"- {item.get('phase', '')}: {item.get('teacher_script', '')}")
            if item.get("expected_student_response"):
                lines.append(f"  - 预期学生回应：{item.get('expected_student_response', '')}" if lang == "zh" else f"  - Expected Student Response: {item.get('expected_student_response', '')}")
            if item.get("key_questions"):
                lines.append("  - 关键追问：" if lang == "zh" else "  - Key Questions:")
                for q in item.get("key_questions", []):
                    lines.append(f"    - {q}")

        lines.extend([
            "",
            "## 分层活动" if lang == "zh" else "## Differentiated Activities",
            f"- 基础层：{plan.get('differentiation', {}).get('basic', '')}" if lang == "zh" else f"- Basic: {plan.get('differentiation', {}).get('basic', '')}",
            f"- 进阶层：{plan.get('differentiation', {}).get('proficient', '')}" if lang == "zh" else f"- Proficient: {plan.get('differentiation', {}).get('proficient', '')}",
            f"- 拓展层：{plan.get('differentiation', {}).get('advanced', '')}" if lang == "zh" else f"- Advanced: {plan.get('differentiation', {}).get('advanced', '')}",
        ])

        lines.extend([
            "",
            "## 评价与作业" if lang == "zh" else "## Assessment and Homework",
            f"- 形成性评价：{plan.get('assessment', {}).get('formative', '')}" if lang == "zh" else f"- Formative: {plan.get('assessment', {}).get('formative', '')}",
            f"- 总结性评价：{plan.get('assessment', {}).get('summative', '')}" if lang == "zh" else f"- Summative: {plan.get('assessment', {}).get('summative', '')}",
            f"- 作业：{plan.get('homework', '')}" if lang == "zh" else f"- Homework: {plan.get('homework', '')}",
        ])

        if plan.get("in_class_quiz"):
            lines.extend(["", "## 随堂测验" if lang == "zh" else "## In-class Quiz"])
            for idx, q in enumerate(plan.get("in_class_quiz", []), start=1):
                if not isinstance(q, dict):
                    continue
                if lang == "zh":
                    lines.append(f"{idx}. （{q.get('type', '')}｜{q.get('difficulty', '')}）{q.get('question', '')}")
                    if q.get("answer"):
                        lines.append(f"   - 参考答案：{q.get('answer', '')}")
                    if q.get("explanation"):
                        lines.append(f"   - 解析：{q.get('explanation', '')}")
                else:
                    lines.append(f"{idx}. ({q.get('type', '')} | {q.get('difficulty', '')}) {q.get('question', '')}")
                    if q.get("answer"):
                        lines.append(f"   - Answer: {q.get('answer', '')}")
                    if q.get("explanation"):
                        lines.append(f"   - Explanation: {q.get('explanation', '')}")

        lines.extend(["", "## 评价量规" if lang == "zh" else "## Assessment Rubric"])
        for item in plan.get("assessment_rubric", []):
            if not isinstance(item, dict):
                continue
            if lang == "zh":
                lines.append(f"- {item.get('criterion', '')}")
                lines.append(f"  - 优秀：{item.get('excellent', '')}")
                lines.append(f"  - 良好：{item.get('good', '')}")
                lines.append(f"  - 待改进：{item.get('needs_improvement', '')}")
            else:
                lines.append(f"- {item.get('criterion', '')}")
                lines.append(f"  - Excellent: {item.get('excellent', '')}")
                lines.append(f"  - Good: {item.get('good', '')}")
                lines.append(f"  - Needs Improvement: {item.get('needs_improvement', '')}")

        if isinstance(plan.get("worksheet"), dict):
            sheet = plan["worksheet"]
            lines.extend(["", "## 学习单/练习单" if lang == "zh" else "## Worksheet"])
            title = str(sheet.get("title", "")).strip()
            if title:
                lines.append(f"- 标题：{title}" if lang == "zh" else f"- Title: {title}")
            for sec in sheet.get("sections", []):
                if not isinstance(sec, dict):
                    continue
                sec_name = sec.get("name", "")
                lines.append(f"### {sec_name}" if sec_name else "###")
                for it in sec.get("items", []):
                    lines.append(f"- {it}")
            if sheet.get("answer_key"):
                lines.extend(["", "### 答案要点" if lang == "zh" else "### Answer Key"])
                for a in sheet.get("answer_key", []):
                    lines.append(f"- {a}")

        lines.extend([
            "",
            "## 板书与资源" if lang == "zh" else "## Board Plan and Resources",
            f"- 板书设计：{plan.get('board_plan', '')}" if lang == "zh" else f"- Board Plan: {plan.get('board_plan', '')}",
        ])
        for item in plan.get("board_outline", []):
            lines.append(f"- {item}")
        for item in plan.get("resources", []):
            lines.append(f"- {item}")

        if self._include_citation and plan.get("references"):
            lines.extend(["", "## 参考依据" if lang == "zh" else "## References"])
            for ref in plan.get("references", []):
                lines.append(f"- {ref}")

        return "\n".join(lines)


class LessonToVideoPromptTool(Tool):
    """Convert lesson-plan text into a storyboard-style video prompt."""

    @staticmethod
    def _guess_lang(text: str) -> str:
        sample = text[:600]
        zh = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
        return "zh" if zh >= 20 else "en"

    async def _llm_generate_prompt(
        self,
        *,
        lang: str,
        lesson_plan: str,
        style: str,
        duration_seconds: int,
        segments_count: int,
        refs: list[str],
    ) -> dict[str, Any] | None:
        config = load_config()
        model = config.agents.defaults.model
        api_key = config.get_api_key(model)
        if not api_key:
            return None
        provider_cfg = config.get_provider(model)
        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=(provider_cfg.extra_headers if provider_cfg else None),
            provider_name=config.get_provider_name(model),
        )

        ref_lines = [str(x).strip()[:900] for x in refs if str(x).strip()][:10]
        refs_block = ""
        if ref_lines:
            if lang == "zh":
                refs_block = "可参考的材料片段（如不相关可忽略，禁止编造来源）：\n" + "\n".join(
                    f"- {x}" for x in ref_lines
                )
            else:
                refs_block = "Reference snippets (ignore if irrelevant, do not fabricate sources):\n" + "\n".join(
                    f"- {x}" for x in ref_lines
                )

        clip = lesson_plan.strip()
        if len(clip) > 7000:
            clip = clip[:7000]

        if lang == "zh":
            system = "你是教学视频分镜与旁白脚本专家。只输出严格JSON，不要代码块，不要额外解释。"
            user = (
                "请把下面的教案文本转为可直接用于逐段生成短视频片段的分镜稿（每段2–10秒）。\n"
                "硬性要求：\n"
                "1) 输出严格JSON，字段缺失也要给空值。\n"
                "2) 生成分镜段数约等于 segments_count，按课堂流程覆盖“导入/新授/练习/总结评价”。\n"
                "3) 每段必须包含：shot_id、stage_tag、duration_sec(2-10)、scene_text、voiceover_full、on_screen_text、camera、assets_hint、transition、search_keywords、video_gen_prompt。\n"
                "4) voiceover_full 要口语化、面向学生、含至少1个具体例子或类比；on_screen_text 需简短高对比（不超过20字）。\n"
                "5) video_gen_prompt 是给视频生成模型的英文提示词，必须包含风格、镜头、画面主体、环境、字幕/板书呈现方式、避免错误元素（如乱码、错字、低清、抖动）。\n"
                "6) search_keywords 用于本地视频库复用检索（3-8个词）。\n"
                f"style={style}\n"
                f"duration_seconds={duration_seconds}\n"
                f"segments_count={segments_count}\n"
                f"{refs_block}\n"
                "教案文本：\n"
                f"{clip}\n"
                "输出JSON结构：\n"
                "{\n"
                '  "video_prompt": {\n'
                '    "video_goal": "...",\n'
                '    "style": "...",\n'
                '    "duration_seconds": 60,\n'
                '    "segments": [\n'
                "      {\n"
                '        "segment": 1,\n'
                '        "shot_id": "shot-1",\n'
                '        "stage_tag": "导入",\n'
                '        "duration_sec": 6,\n'
                '        "camera": "...",\n'
                '        "scene_text": "...",\n'
                '        "voiceover_full": "...",\n'
                '        "on_screen_text": "...",\n'
                '        "assets_hint": "...",\n'
                '        "transition": "...",\n'
                '        "search_keywords": ["..."],\n'
                '        "video_gen_prompt": "...",\n'
                '        "selected": true\n'
                "      }\n"
                "    ],\n"
                '    "materials_refs": ["..."],\n'
                '    "source_excerpt": "..." \n'
                "  }\n"
                "}\n"
            )
        else:
            system = "You are an expert storyboarder for educational short clips. Output strict JSON only. No code fences."
            user = (
                "Convert the lesson-plan text into a storyboard for generating short video clips (each 2–10 seconds).\n"
                "Hard requirements:\n"
                "1) Output strict JSON only.\n"
                "2) Produce about segments_count segments covering intro / instruction / practice / wrap-up.\n"
                "3) Each segment must include: shot_id, stage_tag, duration_sec(2-10), scene_text, voiceover_full, on_screen_text, camera, assets_hint, transition, search_keywords, video_gen_prompt.\n"
                "4) voiceover_full should be student-friendly and include at least one concrete example or analogy.\n"
                "5) video_gen_prompt must be an English prompt for a video generator, including style, camera, subject, environment, subtitle/board-text rendering, and negatives (garbled text, low-res, jitter).\n"
                "6) search_keywords are for local video reuse search (3–8 tokens).\n"
                f"style={style}\n"
                f"duration_seconds={duration_seconds}\n"
                f"segments_count={segments_count}\n"
                f"{refs_block}\n"
                "Lesson plan text:\n"
                f"{clip}\n"
                "Output JSON shape:\n"
                "{\n"
                '  "video_prompt": {\n'
                '    "video_goal": "...",\n'
                '    "style": "...",\n'
                '    "duration_seconds": 60,\n'
                '    "segments": [{"segment": 1, "shot_id": "shot-1", "stage_tag": "Intro", "duration_sec": 6, "camera": "...", "scene_text": "...", "voiceover_full": "...", "on_screen_text": "...", "assets_hint": "...", "transition": "...", "search_keywords": ["..."], "video_gen_prompt": "...", "selected": true}],\n'
                '    "materials_refs": ["..."],\n'
                '    "source_excerpt": "..."\n'
                "  }\n"
                "}\n"
            )

        try:
            resp = await provider.chat(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=None,
                model=model,
                max_tokens=4096,
                temperature=0.2,
                tool_choice="none",
            )
            content = (resp.content or "").strip()
            if not content:
                return None
            data = json_repair.loads(content)
            if isinstance(data, dict):
                vp = data.get("video_prompt")
                return vp if isinstance(vp, dict) else None
            return None
        except Exception:
            return None

    @staticmethod
    async def _auto_retrieve_materials(*, query: str, top_k: int = 6) -> list[str]:
        try:
            cfg = load_config()
            if not getattr(cfg, "education", None) or not cfg.education.enabled:
                return []
            workspace = cfg.workspace_path.resolve()
            vectordb_rel = str(cfg.education.vectors.path)
            collection_name = str(cfg.education.vectors.collection)
            top_k = max(1, min(12, int(top_k)))

            if getattr(cfg.education, "auto_import_materials", True):
                materials_dir = str(getattr(cfg.education, "materials_dir", "documents/materials") or "").strip()
                if materials_dir:
                    try:
                        from pathlib import Path

                        from nanobot.agent.tools.education_document import DocumentImportDirTool

                        p = Path(materials_dir).expanduser()
                        if not p.is_absolute():
                            (workspace / p).resolve().mkdir(parents=True, exist_ok=True)

                        importer = DocumentImportDirTool(
                            workspace=workspace,
                            vectordb_path=vectordb_rel,
                            collection_name=collection_name,
                        )
                        await importer.execute(path=materials_dir, recursive=True, max_files=200)
                    except Exception:
                        pass

            vectordb_path = (workspace / vectordb_rel).resolve()
            try:
                import chromadb
            except Exception:
                return []
            vectordb_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(vectordb_path))
            collection = client.get_or_create_collection(name=collection_name)

            result = collection.query(
                query_texts=[query[:1200]],
                n_results=top_k,
                where=None,
                include=["documents", "metadatas", "distances"],
            )
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            dists = result.get("distances", [[]])[0]
            refs: list[str] = []
            for doc, meta, dist in zip(docs, metas, dists, strict=False):
                if not doc:
                    continue
                m = meta or {}
                src = str(m.get("source_path", "")).strip()
                score = round(1.0 - float(dist), 4) if dist is not None else None
                snippet = str(doc).strip().replace("\n", " ")
                snippet = snippet[:700]
                prefix = f"[{src} | score={score}]" if src else f"[score={score}]"
                refs.append(f"{prefix} {snippet}")
            return refs
        except Exception:
            return []

    @property
    def name(self) -> str:
        return "lesson_to_video_prompt"

    @property
    def description(self) -> str:
        return "Transform a lesson plan into storyboard prompts for educational videos."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "lesson_plan": {"type": "string", "description": "Lesson plan content"},
                "style": {"type": "string", "description": "Video style, e.g., realistic/cartoon"},
                "duration_seconds": {"type": "integer", "minimum": 5, "maximum": 600},
            },
            "required": ["lesson_plan"],
        }

    async def execute(
        self,
        lesson_plan: str,
        style: str = "educational cinematic",
        duration_seconds: int = 60,
        **kwargs: Any,
    ) -> str:
        lang = self._guess_lang(lesson_plan)
        cleaned = " ".join(lesson_plan.split())
        refs = await self._auto_retrieve_materials(query=cleaned, top_k=6)
        core = lesson_plan.strip().replace("\r\n", "\n")
        excerpt = " ".join(core.split())[:1400]
        segments_count = max(4, min(12, max(4, duration_seconds // 7)))

        llm_prompt = await self._llm_generate_prompt(
            lang=lang,
            lesson_plan=core,
            style=style,
            duration_seconds=duration_seconds,
            segments_count=segments_count,
            refs=refs,
        )
        if isinstance(llm_prompt, dict):
            llm_prompt.setdefault("style", style)
            llm_prompt.setdefault("duration_seconds", duration_seconds)
            llm_prompt.setdefault("materials_refs", refs[:10])
            llm_prompt.setdefault("source_excerpt", excerpt)
            segments = llm_prompt.get("segments")
            if isinstance(segments, list):
                for i, seg in enumerate(segments, start=1):
                    if not isinstance(seg, dict):
                        continue
                    seg.setdefault("segment", i)
                    seg.setdefault("shot_id", f"shot-{i}")
                    seg.setdefault("selected", True)
                    d = seg.get("duration_sec", seg.get("duration", 6))
                    try:
                        d_int = int(d)
                    except Exception:
                        d_int = 6
                    d_int = max(2, min(10, d_int))
                    seg["duration_sec"] = d_int
                    seg["duration"] = d_int
            return json.dumps({"status": "ok", "video_prompt": llm_prompt}, ensure_ascii=False)

        phase_tags = ["导入", "新授", "练习", "总结与评价"] if lang == "zh" else ["Intro", "Instruction", "Practice", "Wrap-up"]
        base_duration = max(2, min(10, max(5, duration_seconds // segments_count)))
        prompt = {
            "video_goal": "Create an educational explainer video",
            "style": style,
            "duration_seconds": duration_seconds,
            "segments": [],
            "source_excerpt": excerpt,
            "materials_refs": refs[:10],
        }
        for idx in range(segments_count):
            stage = phase_tags[idx % len(phase_tags)]
            kp = f"{stage}要点" if lang == "zh" else f"{stage} key point"
            on_screen = kp[:18] if lang == "zh" else kp[:22]
            prompt["segments"].append(
                {
                    "segment": idx + 1,
                    "shot_id": f"shot-{idx + 1}",
                    "duration": base_duration,
                    "duration_sec": base_duration,
                    "camera": "medium shot, smooth dolly, stable framing",
                    "scene_text": f"{stage}：用板书/图示呈现{kp}，配合课堂情境素材",
                    "voiceover_full": f"用学生听得懂的话解释{kp}，并给出一个具体例子或类比。",
                    "on_screen_text": on_screen,
                    "assets_hint": "Simple diagrams, high-contrast labels, clean classroom background",
                    "transition": "smooth dissolve",
                    "stage_tag": stage,
                    "search_keywords": [stage, "板书", "图示", "讲解"] if lang == "zh" else [stage, "whiteboard", "diagram", "explain"],
                    "video_gen_prompt": (
                        f"Educational cinematic style, {stage} segment. Medium shot, stable camera, clean classroom background. "
                        f"Show a teacher hand drawing clear diagrams and labels on a whiteboard. On-screen subtitle: '{on_screen}'. "
                        "High contrast, sharp focus, smooth motion, no garbled text, no misspellings, no jitter, no low resolution."
                    ),
                    "selected": True,
                }
            )
        return json.dumps({"status": "ok", "video_prompt": prompt}, ensure_ascii=False)


class MediaGenerateTool(Tool):
    """Call ARK (Volcano Engine) image/video generation APIs."""

    _DEFAULT_VIDEO_MODEL = "doubao-seedance-1-0-pro-250528"

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        image_model: str = "doubao-seedream-5-0-260128",
        video_model: str = "doubao-seedance-1-0-pro-250528",
        timeout_seconds: int = 60,
        task_poll_interval_seconds: int = 5,
        task_max_wait_seconds: int = 300,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._image_model = image_model
        self._video_model = video_model
        self._timeout = timeout_seconds
        self._poll_interval = task_poll_interval_seconds
        self._max_wait = task_max_wait_seconds

    @property
    def name(self) -> str:
        return "media_generate"

    @property
    def description(self) -> str:
        return (
            "Generate image or video assets via ARK (Volcano Engine) APIs. "
            "Images are returned synchronously. Videos are submitted as async tasks — "
            "the tool returns a task_id; use media_query_task to poll for completion."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "media_type": {"type": "string", "enum": ["image", "video"]},
                "prompt": {"type": "string"},
                "size": {
                    "type": "string",
                    "description": "Image size/resolution, e.g. '2K', '1024x1024'",
                    "default": "2K",
                },
                "ratio": {
                    "type": "string",
                    "description": "Video aspect ratio, e.g. '16:9', '9:16', '1:1'",
                    "default": "16:9",
                },
                "duration": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 10,
                    "description": "Video duration in seconds (ARK accepts 2–10)",
                    "default": 5,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["png", "jpg", "webp"],
                    "default": "png",
                },
                "watermark": {"type": "boolean", "default": False},
                "model": {"type": "string", "description": "Optional model override"},
            },
            "required": ["media_type", "prompt"],
        }

    async def execute(
        self,
        media_type: str,
        prompt: str,
        size: str = "2K",
        ratio: str = "16:9",
        duration: int = 5,
        output_format: str = "png",
        watermark: bool = False,
        model: str = "",
        **kwargs: Any,
    ) -> str:
        if not self._base_url:
            return "错误：未配置媒体生成接口。请在配置中设置 education.media.baseUrl 与 education.media.apiKey。"
        if not self._api_key:
            return "错误：缺少媒体生成接口密钥。请在配置中设置 education.media.apiKey。"

        target_model = model or (self._image_model if media_type == "image" else self._video_model)
        target_model = str(target_model or "").strip()
        if media_type == "video":
            lower = target_model.lower()
            if (not lower) or ("seed" in lower and "seedance" not in lower) or ("seedream" in lower):
                target_model = self._video_model.strip() if str(self._video_model or "").strip() else self._DEFAULT_VIDEO_MODEL
            if ("seed" in target_model.lower() and "seedance" not in target_model.lower()) or ("seedream" in target_model.lower()):
                target_model = self._DEFAULT_VIDEO_MODEL
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                if media_type == "image":
                    endpoint = f"{self._base_url}/api/v3/images/generations"
                    payload: dict[str, Any] = {
                        "model": target_model,
                        "prompt": prompt,
                        "size": size,
                        "output_format": output_format,
                        "watermark": watermark,
                    }
                    resp = await client.post(endpoint, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        return f"错误：图片生成接口调用失败（{resp.status_code}）：{resp.text[:500]}"
                    data = resp.json()
                    return json.dumps({"status": "ok", "media_type": "image", "result": data}, ensure_ascii=False)
                else:
                    endpoint = f"{self._base_url}/api/v3/contents/generations/tasks"
                    payload = {
                        "model": target_model,
                        "content": [{"type": "text", "text": prompt}],
                        "ratio": ratio,
                        "duration": duration,
                        "watermark": watermark,
                    }
                    resp = await client.post(endpoint, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        retry_model = self._DEFAULT_VIDEO_MODEL
                        should_retry = (
                            resp.status_code == 400
                            and retry_model
                            and retry_model != target_model
                            and ("does not support content generation" in resp.text.lower() or "\"param\":\"model\"" in resp.text)
                        )
                        if should_retry:
                            payload["model"] = retry_model
                            resp2 = await client.post(endpoint, headers=headers, json=payload)
                            if resp2.status_code < 400:
                                data = resp2.json()
                                task_id = data.get("id") or data.get("task_id") or ""
                                return json.dumps(
                                    {
                                        "status": "submitted",
                                        "media_type": "video",
                                        "task_id": task_id,
                                        "message": f"已自动切换为可用的视频模型（{retry_model}）并重新提交任务。",
                                        "raw": data,
                                    },
                                    ensure_ascii=False,
                                )
                        return f"错误：视频任务提交失败（{resp.status_code}）：{resp.text[:500]}"
                    data = resp.json()
                    task_id = data.get("id") or data.get("task_id") or ""
                    return json.dumps({
                        "status": "submitted",
                        "media_type": "video",
                        "task_id": task_id,
                        "message": f"视频任务已提交。可使用 media_query_task(task_id='{task_id}') 查询进度。",
                        "raw": data,
                    }, ensure_ascii=False)
        except Exception as exc:
            return f"错误：媒体生成失败：{exc}"


class MediaQueryTaskTool(Tool):
    """Query the status and result of an ARK async video generation task."""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        task_poll_interval_seconds: int = 5,
        task_max_wait_seconds: int = 300,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._poll_interval = task_poll_interval_seconds
        self._max_wait = task_max_wait_seconds

    @property
    def name(self) -> str:
        return "media_query_task"

    @property
    def description(self) -> str:
        return (
            "Query the status of an ARK async video generation task. "
            "Set wait=true to poll until completion (up to task_max_wait_seconds)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID returned by media_generate"},
                "wait": {
                    "type": "boolean",
                    "description": "If true, poll until task completes or times out",
                    "default": False,
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, task_id: str, wait: bool = False, **kwargs: Any) -> str:
        import asyncio

        if not self._base_url:
            return "Error: media API is not configured."
        if not self._api_key:
            return "Error: media API key missing."

        endpoint = f"{self._base_url}/api/v3/contents/generations/tasks/{task_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        elapsed = 0
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    resp = await client.get(endpoint, headers=headers)
                    if resp.status_code >= 400:
                        return f"Error: task query failed ({resp.status_code}): {resp.text[:500]}"
                    data = resp.json()
                    status = data.get("status", "")
                    if not wait or status in ("succeeded", "failed", "cancelled"):
                        return json.dumps({"status": status, "task_id": task_id, "result": data}, ensure_ascii=False)
                    if elapsed >= self._max_wait:
                        return json.dumps({
                            "status": "timeout",
                            "task_id": task_id,
                            "message": f"Task not completed after {self._max_wait}s",
                            "last_status": status,
                        }, ensure_ascii=False)
                    await asyncio.sleep(self._poll_interval)
                    elapsed += self._poll_interval
        except Exception as exc:
            return f"Error: task query failed: {exc}"
