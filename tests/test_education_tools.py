import asyncio
import json
from pathlib import Path

from nanobot.agent.tools.education_document import DocumentImportTool, DocumentSearchTool
from nanobot.agent.tools.education_lesson import LessonPlanGenerateTool


class _FakeCollection:
    def __init__(self):
        self._rows = []

    def add(self, ids, documents, metadatas):
        for i, d, m in zip(ids, documents, metadatas, strict=False):
            self._rows.append({"id": i, "document": d, "metadata": m})

    def delete(self, where):
        key, value = next(iter(where.items()))
        self._rows = [r for r in self._rows if r["metadata"].get(key) != value]

    def query(self, query_texts, n_results, where=None, include=None):
        rows = self._rows
        if where:
            for key, value in where.items():
                rows = [r for r in rows if r["metadata"].get(key) == value]
        rows = rows[:n_results]
        return {
            "documents": [[r["document"] for r in rows]],
            "metadatas": [[r["metadata"] for r in rows]],
            "distances": [[0.1 for _ in rows]],
        }


def test_document_import_and_search(monkeypatch, tmp_path: Path):
    fake = _FakeCollection()
    sample = tmp_path / "math.md"
    sample.write_text("一次函数 斜率 截距 图像 性质 应用", encoding="utf-8")

    import_tool = DocumentImportTool(workspace=tmp_path)
    search_tool = DocumentSearchTool(workspace=tmp_path)

    monkeypatch.setattr(import_tool, "_get_collection", lambda: fake)
    monkeypatch.setattr(search_tool, "_get_collection", lambda: fake)

    out = asyncio.run(import_tool.execute(path="math.md", subject="math", grade="7"))
    assert '"status": "ok"' in out

    result = asyncio.run(search_tool.execute(query="一次函数", top_k=3, subject="math"))
    assert '"hits"' in result
    assert "一次函数" in result


def test_lesson_plan_generate_has_required_sections():
    tool = LessonPlanGenerateTool(default_language="zh", output_format="markdown")
    out = asyncio.run(tool.execute(
        subject="初中数学",
        grade="七年级",
        topic="一次函数",
        duration_minutes=45,
    ))

    assert "## 学习目标" in out
    assert "## 教学流程" in out
    assert "## 评价与作业" in out


def test_lesson_plan_generate_advanced_json_contains_prompt_and_mode_process():
    tool = LessonPlanGenerateTool(default_language="zh", output_format="json")
    out = asyncio.run(tool.execute(
        subject="初中数学",
        grade="七年级",
        topic="一次函数",
        duration_minutes=45,
        teaching_mode="讲授型",
        teaching_objectives=[
            "学生能够识别一次函数表达式",
            "学生能够在情境中建立一次函数模型",
        ],
        prior_knowledge=["已掌握坐标系"],
        learner_misconceptions=["容易忽略定义域条件"],
        learner_interests=["对生活建模任务感兴趣"],
        selected_activities=["精讲串联", "对比讲解", "当堂检测"],
        needs_quiz=True,
        needs_rubric=True,
        needs_differentiation=True,
    ))

    parsed = json.loads(out)
    plan = parsed["lesson_plan"]
    assert parsed["status"] == "ok"
    assert "generation_prompt" in parsed
    assert "讲授型" in str(plan.get("teaching_mode", ""))
    assert isinstance(plan.get("teaching_process"), list)
    total = sum(int(x.get("minutes", 0)) for x in plan["teaching_process"])
    assert total == 45


def test_lesson_plan_prompt_includes_four_layer_teacher_persona():
    tool = LessonPlanGenerateTool(default_language="zh", output_format="json")
    out = asyncio.run(tool.execute(
        subject="初中数学",
        grade="七年级",
        topic="一次函数",
        duration_minutes=45,
        teacher_profile={
            "teaching_style": "探究式",
            "persona": {
                "basic_attributes": {
                    "subject": "数学",
                    "grade_level": "7年级",
                    "class_atmosphere": "活跃互动",
                },
                "teaching_style": {
                    "method_preference": "探究式",
                    "interaction_pattern": "师生互动频繁",
                },
                "professional_competence": {
                    "experience_level": "熟手教师",
                    "development_goals": ["加强核心素养渗透"],
                },
                "implicit_preferences": {
                    "education_philosophy": "建构主义",
                },
            },
        },
    ))

    parsed = json.loads(out)
    prompt = parsed.get("generation_prompt", "")
    assert "教师画像摘要" in prompt
    assert "method_preference=探究式" in prompt
    assert "experience_level=熟手教师" in prompt
    assert "education_philosophy=建构主义" in prompt
