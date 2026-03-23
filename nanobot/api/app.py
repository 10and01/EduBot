"""FastAPI app for chat, config, skills, MCP, and local file management."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from nanobot.agent.loop import AgentLoop
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.lesson_validation import validate_lesson_plan
from nanobot.agent.tools.teaching_modes import get_mode_activity_pack
from nanobot.agent.tools.template_recommender import list_activity_packs, list_lesson_templates
from nanobot.bus.queue import MessageBus
from nanobot.cli.commands import _make_provider
from nanobot.config.loader import get_config_path, load_config, save_config, set_config_path
from nanobot.config.schema import Config
from nanobot.providers.litellm_provider import LiteLLMProvider


_GLOBAL_TEACHER_PROFILE_KEY = "__global_teacher__"
_GLOBAL_PROFILE_REFRESH_TASK: asyncio.Task[None] | None = None
_STORYBOARD_VIDEO_QUEUE_TASKS: dict[str, asyncio.Task[None]] = {}
_MATERIALS_VIDEO_CACHE: dict[str, Any] = {"expires_at": 0.0, "files": []}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_key: str = "web:default"


class ChatResponse(BaseModel):
    response: str
    trace: list[dict[str, Any]] = Field(default_factory=list)


class DocumentImportRequest(BaseModel):
    path: str = Field(min_length=1)
    subject: str = ""
    grade: str = ""

class DocumentImportDirRequest(BaseModel):
    path: str = Field(min_length=1)
    recursive: bool = True
    max_files: int = Field(default=200, ge=1, le=500)
    subject: str = ""
    grade: str = ""


class DocumentQueryRequest(BaseModel):
    query: str = ""
    mode: str = "vector"  # vector | index
    top_k: int = 5
    subject: str = ""
    grade: str = ""


class SkillUpdateRequest(BaseModel):
    content: str
    source: str = "auto"


class MCPConfigUpdateRequest(BaseModel):
    servers: dict[str, Any] = Field(default_factory=dict)


class TeacherProfileUpdateRequest(BaseModel):
    session_key: str = "web:default"
    persona: dict[str, Any] = Field(default_factory=dict)
    teacher_name: str = ""
    subject: str = ""
    grade_level: str = ""
    teaching_style: str = ""
    duration_preference: str = ""
    assessment_preference: str = ""
    video_style_preference: str = ""
    special_needs: str = ""


class StoryboardSegmentUpdateRequest(BaseModel):
    scene_text: str | None = None
    voiceover_full: str | None = None
    on_screen_text: str | None = None
    transition: str | None = None
    duration_sec: int | None = Field(default=None, ge=2, le=120)
    selected: bool | None = None


class StoryboardCreateRequest(BaseModel):
    lesson_plan: str = Field(min_length=1)
    style: str = "educational cinematic"
    duration_seconds: int = Field(default=60, ge=5, le=600)


class StoryboardGenerateVideoRequest(BaseModel):
    style: str = "educational cinematic"
    ratio: str = "16:9"
    duration: int = Field(default=5, ge=2, le=10)
    only_selected: bool = True


class VideoLibrarySaveRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    task_id: str = ""
    video_url: str = ""
    subject: str = ""
    grade: str = ""
    tags: list[str] = Field(default_factory=list)


class VideoImportLocalRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    subject: str = ""
    grade: str = ""
    tags: list[str] = Field(default_factory=list)


class ExportLessonVideoRequest(BaseModel):
    lesson_content: str = Field(min_length=1)
    mappings: list[dict[str, str]] = Field(default_factory=list)
    format: str = "markdown"
    title: str = "教案与视频映射"


class AdvancedLessonPlanRequest(BaseModel):
    session_key: str = "web:default"
    subject: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    duration_minutes: int = Field(default=45, ge=1, le=300)

    learning_objectives: list[str] = Field(default_factory=list)
    prior_knowledge: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)

    key_points: list[str] = Field(default_factory=list)
    difficulties: list[str] = Field(default_factory=list)
    teaching_mode: str = "讲授型"
    selected_activities: list[str] = Field(default_factory=list)

    needs_quiz: bool = False
    needs_rubric: bool = False
    needs_differentiation: bool = False

    references: list[str] = Field(default_factory=list)
    language: str = "zh"


class LessonTemplateQueryRequest(BaseModel):
    subject: str = ""
    grade: str = ""
    teaching_mode: str = ""
    topic: str = ""
    limit: int = Field(default=20, ge=1, le=100)


class ActivityPackQueryRequest(BaseModel):
    subject: str = ""
    teaching_mode: str = ""
    limit: int = Field(default=50, ge=1, le=200)


class LessonTemplateCreateRequest(BaseModel):
    id: str = ""
    subject: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    teaching_mode: str = Field(min_length=1)
    content: str = Field(min_length=1)
    key_activities: list[str] = Field(default_factory=list)
    time_allocation: dict[str, int] = Field(default_factory=dict)
    assessment_type: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    quality_score: float = Field(default=4.0, ge=0.0, le=5.0)


class ActivityPackCreateRequest(BaseModel):
    id: str = ""
    teaching_mode: str = Field(min_length=1)
    subject: str = "通用"
    activity: str = Field(min_length=1)
    suggested_minutes: int = Field(default=10, ge=1, le=180)
    grouping: str = "全班"
    output: str = ""
    notes: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_session_name(session_key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", session_key)


def _workspace_base() -> Path:
    cfg = runtime.config
    if not cfg:
        raise HTTPException(status_code=500, detail="runtime config not ready")
    return cfg.workspace_path.resolve()


def _teacher_profile_path(session_key: str) -> Path:
    base = _workspace_base()
    folder = base / "teacher_profiles"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_safe_session_name(session_key)}.json"


def _teacher_profile_key(session_key: str) -> str:
    if session_key.startswith("web:"):
        return _GLOBAL_TEACHER_PROFILE_KEY
    return session_key


def _get_teacher_profile(session_key: str) -> dict[str, Any]:
    return _read_teacher_profile(_teacher_profile_key(session_key))


def _put_teacher_profile(session_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _save_teacher_profile(_teacher_profile_key(session_key), payload)


def _default_teacher_persona() -> dict[str, Any]:
    return {
        "basic_attributes": {
            "subject": "",
            "grade_level": "",
            "student_profile": "",
            "class_atmosphere": "",
            "course_duration": "",
            "resource_constraints": "",
        },
        "teaching_style": {
            "method_preference": "",
            "interaction_pattern": "",
            "assessment_preference": "",
            "language_style": "",
        },
        "professional_competence": {
            "experience_level": "",
            "development_goals": [],
            "strengths": [],
            "improvement_areas": [],
        },
        "implicit_preferences": {
            "education_philosophy": "",
            "good_lesson_definition": "",
            "personal_interests": [],
        },
    }


def _normalize_teacher_profile(session_key: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    base = payload if isinstance(payload, dict) else {}
    persona = _default_teacher_persona()
    src_persona = base.get("persona")
    if isinstance(src_persona, dict):
        for section, values in src_persona.items():
            if isinstance(values, dict) and section in persona:
                persona[section].update(values)

    # Backward-compatible field mapping.
    if str(base.get("subject", "")).strip() and not str(persona["basic_attributes"].get("subject", "")).strip():
        persona["basic_attributes"]["subject"] = str(base.get("subject", "")).strip()
    if str(base.get("grade_level", "")).strip() and not str(persona["basic_attributes"].get("grade_level", "")).strip():
        persona["basic_attributes"]["grade_level"] = str(base.get("grade_level", "")).strip()
    if str(base.get("duration_preference", "")).strip() and not str(persona["basic_attributes"].get("course_duration", "")).strip():
        persona["basic_attributes"]["course_duration"] = str(base.get("duration_preference", "")).strip()
    if str(base.get("teaching_style", "")).strip() and not str(persona["teaching_style"].get("method_preference", "")).strip():
        persona["teaching_style"]["method_preference"] = str(base.get("teaching_style", "")).strip()
    if str(base.get("assessment_preference", "")).strip() and not str(persona["teaching_style"].get("assessment_preference", "")).strip():
        persona["teaching_style"]["assessment_preference"] = str(base.get("assessment_preference", "")).strip()
    if str(base.get("special_needs", "")).strip() and not str(persona["basic_attributes"].get("resource_constraints", "")).strip():
        persona["basic_attributes"]["resource_constraints"] = str(base.get("special_needs", "")).strip()

    normalized = {
        **base,
        "session_key": session_key,
        "teacher_name": str(base.get("teacher_name", "")).strip(),
        "subject": str(base.get("subject", persona["basic_attributes"].get("subject", ""))).strip(),
        "grade_level": str(base.get("grade_level", persona["basic_attributes"].get("grade_level", ""))).strip(),
        "teaching_style": str(base.get("teaching_style", persona["teaching_style"].get("method_preference", ""))).strip(),
        "duration_preference": str(base.get("duration_preference", persona["basic_attributes"].get("course_duration", ""))).strip(),
        "assessment_preference": str(base.get("assessment_preference", persona["teaching_style"].get("assessment_preference", ""))).strip(),
        "video_style_preference": str(base.get("video_style_preference", "")).strip(),
        "special_needs": str(base.get("special_needs", "")).strip(),
        "persona": persona,
    }
    normalized.setdefault("created_at", _now_iso())
    normalized.setdefault("updated_at", _now_iso())
    return normalized


def _read_teacher_profile(session_key: str) -> dict[str, Any]:
    file_path = _teacher_profile_path(session_key)
    if not file_path.exists():
        return _normalize_teacher_profile(
            session_key,
            {"session_key": session_key, "created_at": _now_iso(), "updated_at": _now_iso()},
        )
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return _normalize_teacher_profile(session_key, payload)
    except Exception:
        pass
    return _normalize_teacher_profile(
        session_key,
        {"session_key": session_key, "created_at": _now_iso(), "updated_at": _now_iso()},
    )


def _save_teacher_profile(session_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_teacher_profile(session_key)
    merged = {**current, **payload}
    merged = _normalize_teacher_profile(session_key, merged)
    merged["updated_at"] = _now_iso()
    _teacher_profile_path(session_key).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def _update_profile_from_message(session_key: str, message: str) -> dict[str, Any]:
    msg = message.strip()
    if not msg:
        return _read_teacher_profile(session_key)
    updates: dict[str, Any] = {}
    profile = _read_teacher_profile(session_key)
    persona = _default_teacher_persona()
    current_persona = profile.get("persona")
    if isinstance(current_persona, dict):
        for section, values in current_persona.items():
            if section in persona and isinstance(values, dict):
                persona[section].update(values)

    # Lightweight heuristics; user can always override via questionnaire endpoint.
    subject_map = {
        "数学": "数学", "math": "数学",
        "物理": "物理", "physics": "物理",
        "化学": "化学", "chemistry": "化学",
        "生物": "生物", "biology": "生物",
        "英语": "英语", "english": "英语",
        "语文": "语文", "chinese": "语文",
        "历史": "历史", "history": "历史",
    }
    lower = msg.lower()
    for k, v in subject_map.items():
        if k in lower or k in msg:
            updates["subject"] = v
            persona["basic_attributes"]["subject"] = v
            break

    grade_match = re.search(r"([1-9]|[1-9][0-2])\s*年级|grade\s*([1-9]|1[0-2])", lower)
    if grade_match:
        g = grade_match.group(1) or grade_match.group(2)
        updates["grade_level"] = f"{g}年级"
        persona["basic_attributes"]["grade_level"] = f"{g}年级"

    if "探究" in msg or "inquiry" in lower:
        updates["teaching_style"] = "探究式"
        persona["teaching_style"]["method_preference"] = "探究式"
    elif "讲授" in msg or "lecture" in lower:
        updates["teaching_style"] = "讲授式"
        persona["teaching_style"]["method_preference"] = "讲授式"
    elif "合作" in msg or "collaborative" in lower:
        updates["teaching_style"] = "合作式"
        persona["teaching_style"]["method_preference"] = "合作式"

    duration_match = re.search(r"(\d{2,3})\s*分钟", msg)
    if duration_match:
        updates["duration_preference"] = f"{duration_match.group(1)}分钟"
        persona["basic_attributes"]["course_duration"] = f"{duration_match.group(1)}分钟"

    if "形成性" in msg or "formative" in lower:
        updates["assessment_preference"] = "形成性评价优先"
        persona["teaching_style"]["assessment_preference"] = "形成性评价优先"
    elif "总结性" in msg or "summative" in lower:
        updates["assessment_preference"] = "总结性评价优先"
        persona["teaching_style"]["assessment_preference"] = "总结性评价优先"

    if any(x in msg for x in ["活跃", "讨论", "互动", "展示"]) or any(x in lower for x in ["interactive", "discussion"]):
        persona["basic_attributes"]["class_atmosphere"] = "活跃互动"
        persona["teaching_style"]["interaction_pattern"] = "师生互动频繁"
    elif any(x in msg for x in ["沉稳", "安静", "秩序"]) or "structured" in lower:
        persona["basic_attributes"]["class_atmosphere"] = "沉稳有序"
        persona["teaching_style"]["interaction_pattern"] = "教师主导"

    if any(x in msg for x in ["新手教师", "刚入职", "教龄1", "教龄2"]):
        persona["professional_competence"]["experience_level"] = "新手教师"
    elif any(x in msg for x in ["骨干", "教研组长", "资深", "专家"]):
        persona["professional_competence"]["experience_level"] = "专家型教师"

    goal_map = {
        "课堂管理": "提升课堂管理",
        "核心素养": "加强核心素养渗透",
        "跨学科": "探索跨学科融合",
        "信息技术": "提高信息技术应用能力",
    }
    goals = set(persona["professional_competence"].get("development_goals", []))
    for k, v in goal_map.items():
        if k in msg:
            goals.add(v)
    if goals:
        persona["professional_competence"]["development_goals"] = sorted(goals)

    if any(x in msg for x in ["建构主义", "人文主义", "行为主义"]):
        for candidate in ["建构主义", "人文主义", "行为主义"]:
            if candidate in msg:
                persona["implicit_preferences"]["education_philosophy"] = candidate
                break

    if any(x in msg for x in ["思维", "探究", "创造"]):
        persona["implicit_preferences"]["good_lesson_definition"] = "强调学生思维深度发展"
    elif any(x in msg for x in ["高效", "提分", "知识传递"]):
        persona["implicit_preferences"]["good_lesson_definition"] = "强调知识高效传递"

    interests = set(persona["implicit_preferences"].get("personal_interests", []))
    for item in ["历史故事", "科技前沿", "艺术创作", "实验设计"]:
        if item in msg:
            interests.add(item)
    if interests:
        persona["implicit_preferences"]["personal_interests"] = sorted(interests)

    updates["persona"] = persona

    if not updates:
        return profile
    return _save_teacher_profile(session_key, updates)


def _sessions_dir() -> Path:
    base = _workspace_base()
    folder = base / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _list_session_keys(limit: int = 200) -> list[str]:
    out: list[str] = []
    for path in sorted(_sessions_dir().glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as f:
                first = f.readline().strip()
            if not first:
                continue
            meta = json.loads(first)
            if isinstance(meta, dict) and meta.get("_type") == "metadata":
                key = str(meta.get("key", "")).strip()
                if key:
                    out.append(key)
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _collect_recent_dialogue_from_all_sessions(
    *,
    max_sessions: int = 80,
    max_messages: int = 240,
    max_chars_per_message: int = 800,
) -> str:
    keys = _list_session_keys(limit=max(1, max_sessions))
    messages: list[tuple[float, dict[str, str]]] = []
    for key in keys:
        session = runtime.agent.sessions.get_or_create(key) if runtime.agent else None
        if not session:
            continue
        for m in session.messages[-max_messages:]:
            role = str(m.get("role", ""))
            if role not in ("user", "assistant"):
                continue
            content = str(m.get("content", "") or "").strip()
            if not content:
                continue
            ts = m.get("timestamp")
            score = 0.0
            if isinstance(ts, str) and ts.strip():
                try:
                    score = datetime.fromisoformat(ts.strip()).timestamp()
                except Exception:
                    score = 0.0
            messages.append(
                (
                    score,
                    {
                        "session_key": key,
                        "role": role,
                        "content": content[:max_chars_per_message],
                    },
                )
            )

    if not messages:
        return ""

    messages.sort(key=lambda x: x[0])
    tail = [x[1] for x in messages[-max_messages:]]
    lines: list[str] = []
    current_key = ""
    for m in tail:
        if m["session_key"] != current_key:
            current_key = m["session_key"]
            lines.append(f"\n[Session: {current_key}]")
        prefix = "用户" if m["role"] == "user" else "助手"
        lines.append(f"{prefix}: {m['content']}")
    return "\n".join(lines).strip()


def _collect_recent_user_messages_from_all_sessions(
    *,
    max_sessions: int = 200,
    max_messages: int = 300,
    max_chars_per_message: int = 800,
) -> list[str]:
    keys = _list_session_keys(limit=max(1, max_sessions))
    items: list[tuple[float, str]] = []
    for key in keys:
        session = runtime.agent.sessions.get_or_create(key) if runtime.agent else None
        if not session:
            continue
        for m in session.messages[-max_messages:]:
            if str(m.get("role", "")) != "user":
                continue
            content = str(m.get("content", "") or "").strip()
            if not content:
                continue
            ts = m.get("timestamp")
            score = 0.0
            if isinstance(ts, str) and ts.strip():
                try:
                    score = datetime.fromisoformat(ts.strip()).timestamp()
                except Exception:
                    score = 0.0
            items.append((score, content[:max_chars_per_message]))
    items.sort(key=lambda x: x[0])
    return [x[1] for x in items[-max_messages:]]


def _parse_json_maybe(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    try:
        import json_repair  # type: ignore

        data = json_repair.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _llm_profile_from_dialogue(
    *,
    dialogue: str,
    current_profile: dict[str, Any],
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

    system = (
        "你是教师用户画像抽取器。根据多段历史对话，生成并更新教师画像。"
        "只输出严格JSON，不要代码块，不要解释。"
        "如果信息不足，对应字段用空字符串或空数组。不要臆造具体姓名或学校。"
    )
    schema_hint = {
        "teacher_name": "",
        "subject": "",
        "grade_level": "",
        "teaching_style": "",
        "duration_preference": "",
        "assessment_preference": "",
        "video_style_preference": "",
        "special_needs": "",
        "persona": _default_teacher_persona(),
    }
    user = (
        "目标：返回一个JSON对象，字段结构与下面schema_hint一致。\n\n"
        f"schema_hint={json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        f"current_profile={json.dumps(current_profile, ensure_ascii=False)}\n\n"
        "dialogue:\n"
        f"{dialogue}\n"
    )

    resp = await provider.chat_with_retry(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=1800,
        temperature=0.2,
    )
    data = _parse_json_maybe(resp.content or "")
    if not data:
        return None
    if "persona" in data and not isinstance(data.get("persona"), dict):
        data.pop("persona", None)
    cleaned: dict[str, Any] = {}
    for k in (
        "teacher_name",
        "subject",
        "grade_level",
        "teaching_style",
        "duration_preference",
        "assessment_preference",
        "video_style_preference",
        "special_needs",
        "persona",
    ):
        if k in data:
            cleaned[k] = data[k]
    if not cleaned:
        return None
    return cleaned


async def _refresh_global_teacher_profile() -> None:
    dialogue = _collect_recent_dialogue_from_all_sessions()
    if not dialogue.strip():
        return
    current = _read_teacher_profile(_GLOBAL_TEACHER_PROFILE_KEY)
    patch = await _llm_profile_from_dialogue(dialogue=dialogue, current_profile=current)
    if patch:
        _save_teacher_profile(_GLOBAL_TEACHER_PROFILE_KEY, patch)
        return
    for msg in _collect_recent_user_messages_from_all_sessions(max_messages=120):
        _update_profile_from_message(_GLOBAL_TEACHER_PROFILE_KEY, msg)


def _schedule_global_teacher_profile_refresh() -> None:
    global _GLOBAL_PROFILE_REFRESH_TASK
    if _GLOBAL_PROFILE_REFRESH_TASK and not _GLOBAL_PROFILE_REFRESH_TASK.done():
        return

    async def runner() -> None:
        try:
            await _refresh_global_teacher_profile()
        except Exception:
            return

    _GLOBAL_PROFILE_REFRESH_TASK = asyncio.create_task(runner())


def _summarize_teacher_persona(profile: dict[str, Any]) -> str:
    persona = profile.get("persona") if isinstance(profile, dict) else {}
    if not isinstance(persona, dict):
        return ""
    chunks: list[str] = []
    basic = persona.get("basic_attributes", {})
    style = persona.get("teaching_style", {})
    prof = persona.get("professional_competence", {})
    implicit = persona.get("implicit_preferences", {})
    if isinstance(basic, dict):
        if basic.get("subject"):
            chunks.append(f"学科={basic.get('subject')}")
        if basic.get("grade_level"):
            chunks.append(f"学段={basic.get('grade_level')}")
        if basic.get("course_duration"):
            chunks.append(f"课时偏好={basic.get('course_duration')}")
    if isinstance(style, dict):
        if style.get("method_preference"):
            chunks.append(f"教学方法={style.get('method_preference')}")
        if style.get("interaction_pattern"):
            chunks.append(f"互动模式={style.get('interaction_pattern')}")
    if isinstance(prof, dict):
        if prof.get("experience_level"):
            chunks.append(f"经验层级={prof.get('experience_level')}")
        goals = prof.get("development_goals")
        if isinstance(goals, list) and goals:
            chunks.append("发展目标=" + "、".join(str(x) for x in goals[:3]))
    if isinstance(implicit, dict):
        if implicit.get("education_philosophy"):
            chunks.append(f"教育理念={implicit.get('education_philosophy')}")
        if implicit.get("good_lesson_definition"):
            chunks.append(f"好课观={implicit.get('good_lesson_definition')}")
    return "；".join(chunks)


def _storyboards_dir() -> Path:
    base = _workspace_base()
    folder = base / "videos" / "storyboards"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _storyboard_path(storyboard_id: str) -> Path:
    return _storyboards_dir() / f"{storyboard_id}.json"


def _load_storyboard(storyboard_id: str) -> dict[str, Any]:
    path = _storyboard_path(storyboard_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="storyboard not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid storyboard file: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid storyboard payload")
    return payload


def _save_storyboard(storyboard_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload["id"] = storyboard_id
    payload["updated_at"] = _now_iso()
    payload.setdefault("created_at", _now_iso())
    _storyboard_path(storyboard_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _video_library_file() -> Path:
    base = _workspace_base()
    folder = base / "videos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "library.jsonl"


def _templates_dir() -> Path:
    base = _workspace_base()
    folder = base / "templates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _lesson_templates_file() -> Path:
    return _templates_dir() / "lesson_templates.jsonl"


def _activity_packs_file() -> Path:
    return _templates_dir() / "activity_packs.jsonl"


def _append_jsonl(file_path: Path, item: dict[str, Any]) -> dict[str, Any]:
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def _read_video_library() -> list[dict[str, Any]]:
    file_path = _video_library_file()
    if not file_path.exists():
        return []
    items: list[dict[str, Any]] = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict) and not item.get("deleted_at"):
                    items.append(item)
            except Exception:
                continue
    return items


def _append_video_library(item: dict[str, Any]) -> dict[str, Any]:
    item.setdefault("id", str(uuid4()))
    item.setdefault("created_at", _now_iso())
    with open(_video_library_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def _extract_video_url(obj: Any) -> str:
    best: str = ""

    def visit(x: Any) -> None:
        nonlocal best
        if best:
            return
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("http://") or s.startswith("https://"):
                if ".mp4" in s or "video" in s or "mp4" in s:
                    best = s
            return
        if isinstance(x, dict):
            for v in x.values():
                visit(v)
            return
        if isinstance(x, list):
            for v in x:
                visit(v)
            return

    visit(obj)
    return best


def _normalize_tokens(text: str) -> list[str]:
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()
    parts = [p for p in re.split(r"\s+", t) if p]
    return parts[:24]


def _materials_dir() -> Path:
    cfg = runtime.config or load_config()
    base = _workspace_base()
    rel = str(getattr(getattr(cfg, "education", object()), "materials_dir", "documents/materials") or "").strip()
    if not rel:
        rel = "documents/materials"
    p = Path(rel)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _material_video_files(max_files: int = 200) -> list[Path]:
    now = time.time()
    cached_files = _MATERIALS_VIDEO_CACHE.get("files")
    if now < float(_MATERIALS_VIDEO_CACHE.get("expires_at", 0.0)) and isinstance(cached_files, list):
        return [p for p in cached_files if isinstance(p, Path)]

    folder = _materials_dir()
    files: list[Path] = []
    if folder.exists() and folder.is_dir():
        exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
        for p in folder.rglob("*"):
            if len(files) >= max_files:
                break
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)

    _MATERIALS_VIDEO_CACHE["files"] = files
    _MATERIALS_VIDEO_CACHE["expires_at"] = now + 30.0
    return files


def _segment_tokens(segment: dict[str, Any]) -> list[str]:
    search_keywords = segment.get("search_keywords", [])
    if isinstance(search_keywords, list):
        kw = " ".join(str(x) for x in search_keywords if str(x).strip())
    else:
        kw = ""
    fallback = " ".join(
        str(x)
        for x in [
            segment.get("stage_tag", ""),
            segment.get("on_screen_text", ""),
            segment.get("scene_text", ""),
            kw,
        ]
        if str(x).strip()
    )
    return _normalize_tokens(fallback)


def _score_tokens(tokens: list[str], hay: str) -> int:
    h = hay.lower()
    return sum(1 for tok in tokens if tok and tok in h)


def _best_material_video_for_tokens(tokens: list[str]) -> dict[str, Any] | None:
    if not tokens:
        return None
    base = _workspace_base()
    best_path: Path | None = None
    best_score = 0
    for p in _material_video_files(max_files=240):
        rel = ""
        try:
            rel = str(p.resolve().relative_to(base))
        except Exception:
            rel = str(p)
        hay = f"{p.name} {p.parent.name} {rel}"
        score = _score_tokens(tokens, hay)
        if score > best_score:
            best_score = score
            best_path = p

    if not best_path:
        return None
    if best_score < max(2, min(5, len(tokens) // 3 + 1)):
        return None

    rel_path = ""
    try:
        rel_path = str(best_path.resolve().relative_to(base))
    except Exception:
        rel_path = str(best_path.resolve())

    item = {
        "name": best_path.stem,
        "description": f"materials: {rel_path}",
        "task_id": "",
        "video_url": "",
        "tags": ["materials", "reused"],
        "source": "materials",
        "local_path": rel_path,
    }
    items = _read_video_library()
    if not any(str(it.get("local_path", "")).strip() == rel_path for it in items):
        _append_video_library(item)
    return item


def _best_local_video_for_segment(storyboard_id: str, segment: dict[str, Any]) -> dict[str, Any] | None:
    shot_id = str(segment.get("shot_id", "")).strip()
    tag_story = f"storyboard:{storyboard_id}"
    tag_shot = f"shot:{shot_id}" if shot_id else ""

    items = _read_video_library()
    if shot_id:
        for it in items:
            tags = it.get("tags", [])
            if isinstance(tags, list) and tag_story in tags and tag_shot in tags:
                return it

    tokens = _segment_tokens(segment)
    if not tokens:
        return None

    best: dict[str, Any] | None = None
    best_score = 0
    for it in items:
        name = str(it.get("name", "")).lower()
        desc = str(it.get("description", "")).lower()
        tags = " ".join([str(t).lower() for t in it.get("tags", [])])
        hay = f"{name} {desc} {tags}"
        score = sum(1 for tok in tokens if tok in hay)
        if score > best_score:
            best_score = score
            best = it

    if best_score >= max(2, min(5, len(tokens) // 3 + 1)):
        return best
    return _best_material_video_for_tokens(tokens)


async def _download_video_to_workspace(url: str, dest: Path) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return False
                with dest.open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            f.write(chunk)
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


def _compose_segment_prompt(*, segment: dict[str, Any], style: str) -> str:
    if isinstance(segment.get("video_gen_prompt"), str) and segment.get("video_gen_prompt", "").strip():
        return str(segment["video_gen_prompt"]).strip()

    stage = str(segment.get("stage_tag", "")).strip()
    camera = str(segment.get("camera", "")).strip()
    scene = str(segment.get("scene_text", "")).strip()
    voice = str(segment.get("voiceover_full", "")).strip()
    on_screen = str(segment.get("on_screen_text", "")).strip()
    assets = str(segment.get("assets_hint", "")).strip()

    pieces = [
        f"Educational cinematic style: {style}.",
        f"Stage: {stage}." if stage else "",
        f"Camera: {camera}." if camera else "Camera: medium shot, stable framing, smooth motion.",
        f"Scene: {scene}." if scene else "",
        f"On-screen subtitle: '{on_screen}'." if on_screen else "",
        "Render subtitles/board text clearly and correctly, high contrast, no garbled text.",
        f"Visual assets: {assets}." if assets else "Visual assets: clean whiteboard, simple diagrams, clear labels.",
        f"Voiceover script: {voice}." if voice else "",
        "High quality, sharp focus, no jitter, no low resolution, no watermark, no random characters.",
    ]
    return " ".join([p for p in pieces if p])


def _check_lesson_text_quality(lesson_plan: str) -> dict[str, Any]:
    text = lesson_plan.strip()
    checks: list[dict[str, Any]] = []
    score = 0

    def add_check(name: str, ok: bool, hint: str) -> None:
        nonlocal score
        checks.append({"name": name, "ok": ok, "hint": hint})
        score += 1 if ok else 0

    add_check("目标清晰", bool(re.search(r"(学习目标|教学目标|本课目标)", text)), "建议补充学习目标（可量化、可评价）")
    add_check("重难点", bool(re.search(r"(重点|难点|重难点)", text)), "建议明确重点与难点，并给出突破策略")
    add_check("过程完整", bool(re.search(r"(教学过程|教学环节|课堂流程|活动设计)", text)), "建议补充完整的教学流程与环节")
    add_check("时间分配", bool(re.search(r"\d+\s*分钟", text)), "建议标注每个环节的时间分配")
    add_check("评价闭环", bool(re.search(r"(评价|测验|提问|检查理解|成功标准)", text)), "建议加入形成性评价与总结性评价")
    add_check("学情应对", bool(re.search(r"(学情|误区|差异化|分层|支架)", text)), "建议补充学情分析与差异化支持")

    total = len(checks)
    level = "优秀" if score >= total - 1 else ("合格" if score >= total - 2 else "需完善")
    return {"score": score, "total": total, "level": level, "checks": checks}


def _start_storyboard_video_queue(storyboard_id: str, req_payload: dict[str, Any]) -> dict[str, Any]:
    storyboard = _load_storyboard(storyboard_id)
    queue = storyboard.get("video_queue", {})
    if isinstance(queue, dict) and queue.get("status") == "running":
        return queue

    job_id = f"vq-{uuid4().hex[:12]}"
    payload = dict(req_payload or {})
    storyboard["video_queue"] = {
        "job_id": job_id,
        "requested_at": _now_iso(),
        "payload": payload,
        "status": "queued",
        "segments": [],
        "combined_local_path": "",
    }
    storyboard["last_generation"] = {
        "requested_at": _now_iso(),
        "payload": payload,
        "result": {"status": "queued", "job_id": job_id},
    }
    _save_storyboard(storyboard_id, storyboard)

    prev = _STORYBOARD_VIDEO_QUEUE_TASKS.get(storyboard_id)
    if prev and not prev.done():
        try:
            prev.cancel()
        except Exception:
            pass
    task = asyncio.create_task(_run_storyboard_video_queue(storyboard_id, payload))
    _STORYBOARD_VIDEO_QUEUE_TASKS[storyboard_id] = task

    storyboard = _load_storyboard(storyboard_id)
    queue = storyboard.get("video_queue", {})
    return queue if isinstance(queue, dict) else {}


async def _run_storyboard_video_queue(storyboard_id: str, req_payload: dict[str, Any]) -> None:
    await runtime.ensure()
    if not runtime.agent:
        storyboard = _load_storyboard(storyboard_id)
        q = storyboard.get("video_queue", {})
        if isinstance(q, dict):
            q["status"] = "failed"
            q["message"] = "agent not ready"
            q["finished_at"] = _now_iso()
            storyboard["video_queue"] = q
            _save_storyboard(storyboard_id, storyboard)
        return

    req_style = str(req_payload.get("style", "educational cinematic"))
    req_ratio = str(req_payload.get("ratio", "16:9"))
    req_duration = int(req_payload.get("duration", 5) or 5)
    only_selected = bool(req_payload.get("only_selected", True))

    base = _workspace_base()
    renders_dir = base / "videos" / "renders" / storyboard_id
    combined_dir = base / "videos" / "renders" / "combined"
    combined_dir.mkdir(parents=True, exist_ok=True)

    storyboard = _load_storyboard(storyboard_id)
    prompt = storyboard.get("video_prompt", {})
    segments = prompt.get("segments", []) if isinstance(prompt, dict) else []
    if only_selected:
        segments = [x for x in segments if isinstance(x, dict) and bool(x.get("selected", True))]
    else:
        segments = [x for x in segments if isinstance(x, dict)]

    queue = storyboard.get("video_queue", {})
    if not isinstance(queue, dict):
        queue = {}
    seg_states: list[dict[str, Any]] = []
    for seg in segments:
        seg_states.append(
            {
                "shot_id": str(seg.get("shot_id", "")).strip(),
                "stage_tag": str(seg.get("stage_tag", "")).strip(),
                "status": "pending",
                "task_id": "",
                "video_url": "",
                "local_path": "",
                "source": "",
                "error": "",
            }
        )
    queue["segments"] = seg_states
    queue["status"] = "running"
    queue["ratio"] = req_ratio
    queue["style"] = req_style
    queue["started_at"] = queue.get("started_at") or _now_iso()
    queue["finished_at"] = ""
    queue["combined_local_path"] = ""
    storyboard["video_queue"] = queue
    _save_storyboard(storyboard_id, storyboard)

    for idx, seg in enumerate(segments):
        storyboard = _load_storyboard(storyboard_id)
        queue = storyboard.get("video_queue", {})
        if not isinstance(queue, dict):
            queue = {}
        seg_states = queue.get("segments", [])
        if not isinstance(seg_states, list):
            seg_states = []
        while len(seg_states) <= idx:
            seg_states.append(
                {
                    "shot_id": "",
                    "stage_tag": "",
                    "status": "pending",
                    "task_id": "",
                    "video_url": "",
                    "local_path": "",
                    "source": "",
                    "error": "",
                }
            )
        queue["segments"] = seg_states

        state: dict[str, Any] = seg_states[idx] if idx < len(seg_states) and isinstance(seg_states[idx], dict) else {}
        state["status"] = "searching"
        seg_states[idx] = state
        queue["segments"] = seg_states
        storyboard["video_queue"] = queue
        _save_storyboard(storyboard_id, storyboard)

        candidate = _best_local_video_for_segment(storyboard_id, seg)
        if candidate:
            base = _workspace_base()
            local_path = str(candidate.get("local_path", "")).strip()
            video_url = str(candidate.get("video_url", "")).strip()
            if local_path and not (base / local_path).exists():
                local_path = ""
            state.update(
                {
                    "status": "reused",
                    "source": str(candidate.get("source", "local")),
                    "task_id": "",
                    "video_url": video_url,
                    "local_path": local_path,
                    "error": "",
                }
            )
            seg_states[idx] = state
            queue["segments"] = seg_states
            storyboard["video_queue"] = queue
            _save_storyboard(storyboard_id, storyboard)
            continue

        state["status"] = "submitting"
        seg_states[idx] = state
        queue["segments"] = seg_states
        storyboard["video_queue"] = queue
        _save_storyboard(storyboard_id, storyboard)

        duration = seg.get("duration_sec", seg.get("duration", req_duration))
        try:
            duration_int = int(duration)
        except Exception:
            duration_int = req_duration
        duration_int = max(2, min(10, duration_int))

        gen_prompt = _compose_segment_prompt(segment=seg, style=req_style)
        submit_output = await runtime.agent.tools.execute(
            "media_generate",
            {
                "media_type": "video",
                "prompt": gen_prompt,
                "ratio": req_ratio,
                "duration": duration_int,
            },
        )
        if isinstance(submit_output, str) and submit_output.strip().startswith("Error: media API is not configured"):
            state.update(
                {
                    "status": "needs_media_config",
                    "error": "media API 未配置：请在 /api/config 里设置 education.media.baseUrl 与 education.media.apiKey，或导入本地视频库复用。",
                }
            )
            seg_states[idx] = state
            queue["segments"] = seg_states
            storyboard["video_queue"] = queue
            _save_storyboard(storyboard_id, storyboard)
            continue
        if isinstance(submit_output, str) and submit_output.strip().startswith("Error: media API key missing"):
            state.update(
                {
                    "status": "needs_media_config",
                    "error": "media API key 缺失：请在 /api/config 里设置 education.media.apiKey，或导入本地视频库复用。",
                }
            )
            seg_states[idx] = state
            queue["segments"] = seg_states
            storyboard["video_queue"] = queue
            _save_storyboard(storyboard_id, storyboard)
            continue
        try:
            submit_parsed = json.loads(submit_output)
        except Exception:
            submit_parsed = {"raw": submit_output}
        task_id = str(submit_parsed.get("task_id", "")).strip() if isinstance(submit_parsed, dict) else ""
        if not task_id:
            state.update({"status": "failed", "error": str(submit_output)[:800]})
            seg_states[idx] = state
            queue["segments"] = seg_states
            storyboard["video_queue"] = queue
            _save_storyboard(storyboard_id, storyboard)
            continue

        state.update({"status": "waiting", "task_id": task_id, "error": ""})
        seg_states[idx] = state
        queue["segments"] = seg_states
        storyboard["video_queue"] = queue
        _save_storyboard(storyboard_id, storyboard)

        query_output = await runtime.agent.tools.execute("media_query_task", {"task_id": task_id, "wait": True})
        try:
            query_parsed = json.loads(query_output)
        except Exception:
            query_parsed = {"raw": query_output}

        status = str(query_parsed.get("status", "")).strip() if isinstance(query_parsed, dict) else ""
        result = query_parsed.get("result", {}) if isinstance(query_parsed, dict) else {}
        if status != "succeeded":
            state.update({"status": "failed", "error": _trim_trace_content(query_parsed, 1200)})
            seg_states[idx] = state
            queue["segments"] = seg_states
            storyboard["video_queue"] = queue
            _save_storyboard(storyboard_id, storyboard)
            continue

        video_url = _extract_video_url(result)
        local_path = ""
        if video_url:
            shot_id = str(seg.get("shot_id", f"shot-{idx+1}")).strip() or f"shot-{idx+1}"
            safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", shot_id)[:60]
            dest = renders_dir / f"{safe}.mp4"
            ok = await _download_video_to_workspace(video_url, dest)
            if ok:
                local_path = str(dest.relative_to(base))

        stage_tag = str(seg.get("stage_tag", "")).strip()
        shot_id = str(seg.get("shot_id", f"shot-{idx+1}")).strip() or f"shot-{idx+1}"
        tags = [f"storyboard:{storyboard_id}", f"shot:{shot_id}"]
        if stage_tag:
            tags.append(f"stage:{stage_tag}")
        if isinstance(seg.get("search_keywords"), list):
            tags.extend([str(x)[:60] for x in seg.get("search_keywords", []) if str(x).strip()][:8])

        _append_video_library(
            {
                "name": f"{storyboard_id} {shot_id} {stage_tag}".strip(),
                "description": str(seg.get("scene_text", "")).strip()[:500],
                "task_id": task_id,
                "video_url": video_url,
                "tags": tags,
                "source": "generated",
                "local_path": local_path,
            }
        )

        state.update(
            {
                "status": "done",
                "video_url": video_url,
                "local_path": local_path,
                "source": "generated",
                "error": "",
            }
        )
        seg_states[idx] = state
        queue["segments"] = seg_states
        storyboard["video_queue"] = queue
        _save_storyboard(storyboard_id, storyboard)

    storyboard = _load_storyboard(storyboard_id)
    queue = storyboard.get("video_queue", {})
    if not isinstance(queue, dict):
        queue = {}
    seg_states = queue.get("segments", [])
    has_errors = False
    if isinstance(seg_states, list):
        has_errors = any(
            isinstance(s, dict) and str(s.get("status", "")) in {"failed", "needs_media_config"} for s in seg_states
        )
    local_files: list[Path] = []
    if isinstance(seg_states, list):
        for s in seg_states:
            if not isinstance(s, dict):
                continue
            lp = str(s.get("local_path", "")).strip()
            if lp:
                p = (base / lp).resolve()
                try:
                    p.relative_to(base)
                except ValueError:
                    continue
                if p.exists() and p.is_file():
                    local_files.append(p)

    combined_local_path = ""
    if local_files and len(local_files) == len(segments) and shutil.which("ffmpeg"):
        file_list = renders_dir / "concat.txt"
        try:
            renders_dir.mkdir(parents=True, exist_ok=True)
            file_list.write_text("\n".join([f"file '{p.as_posix()}'" for p in local_files]), encoding="utf-8")
            out = combined_dir / f"{storyboard_id}.mp4"
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(file_list), "-c", "copy", str(out)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
                combined_local_path = str(out.relative_to(base))
                _append_video_library(
                    {
                        "name": f"{storyboard_id} 合成视频",
                        "description": "由分镜队列生成后自动拼接",
                        "task_id": "",
                        "video_url": "",
                        "tags": [f"storyboard:{storyboard_id}", "combined"],
                        "source": "combined",
                        "local_path": combined_local_path,
                    }
                )
        except Exception:
            combined_local_path = ""

    queue["combined_local_path"] = combined_local_path
    queue["status"] = "completed_with_errors" if has_errors else "completed"
    queue["finished_at"] = _now_iso()
    storyboard["video_queue"] = queue
    _save_storyboard(storyboard_id, storyboard)


def _render_markdown_export(title: str, lesson_content: str, mappings: list[dict[str, str]]) -> str:
    lines = [f"# {title}", "", "## 教案正文", lesson_content.strip(), "", "## 教学阶段与视频映射"]
    if not mappings:
        lines.extend(["", "- 未提供视频映射。"])
        return "\n".join(lines)

    for idx, item in enumerate(mappings, start=1):
        stage = item.get("stage", "")
        name = item.get("video_name", "")
        url = item.get("video_url", "")
        desc = item.get("description", "")
        lines.extend([
            "",
            f"### {idx}. {stage or f'阶段{idx}'}",
            f"- 视频：{name or '未命名'}",
            f"- 链接：{url or '无'}",
            f"- 说明：{desc or '无'}",
        ])
    return "\n".join(lines)


def _trim_trace_content(content: Any, max_chars: int = 4000) -> str:
    if isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, ensure_ascii=False, indent=2)
        except Exception:
            text = str(content)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def _assistant_trace(message: dict[str, Any]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []

    if message.get("reasoning_content"):
        traces.append(
            {
                "kind": "reasoning",
                "emoji": "🧠",
                "title": "Reasoning",
                "content": _trim_trace_content(message.get("reasoning_content", "")),
            }
        )

    for tc in message.get("tool_calls", []) or []:
        fn = (tc or {}).get("function", {})
        name = fn.get("name", "unknown_tool")
        traces.append(
            {
                "kind": "tool_call",
                "emoji": "🛠️",
                "title": f"Tool Call: {name}",
                "tool_name": name,
                "tool_call_id": (tc or {}).get("id", ""),
                "content": _trim_trace_content(fn.get("arguments", "")),
            }
        )

    if message.get("thinking_blocks"):
        traces.append(
            {
                "kind": "thinking_blocks",
                "emoji": "💭",
                "title": "Thinking Blocks",
                "content": _trim_trace_content(message.get("thinking_blocks")),
            }
        )

    return traces


def _chat_view_from_session(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chat: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role", ""))
        if role == "user":
            chat.append(
                {
                    "role": "user",
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp", ""),
                    "traces": [],
                }
            )
            continue

        if role == "assistant":
            content = m.get("content")
            if content:
                chat.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "timestamp": m.get("timestamp", ""),
                        "traces": _assistant_trace(m),
                    }
                )
            else:
                # Assistant tool-call stubs may have no content but still have trace info.
                traces = _assistant_trace(m)
                if traces:
                    chat.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "timestamp": m.get("timestamp", ""),
                            "traces": traces,
                        }
                    )
            continue

        if role == "tool":
            if chat and chat[-1].get("role") == "assistant":
                chat[-1].setdefault("traces", []).append(
                    {
                        "kind": "tool_result",
                        "emoji": "📦",
                        "title": f"Tool Result: {m.get('name', 'tool')}",
                        "tool_call_id": m.get("tool_call_id", ""),
                        "content": _trim_trace_content(m.get("content", "")),
                    }
                )

    return chat


def _append_session_message(session: Any, role: str, content: str) -> None:
    if hasattr(session, "add_message"):
        try:
            session.add_message(role, content)
            return
        except Exception:
            pass
    if not hasattr(session, "messages"):
        return
    session.messages.append({"role": role, "content": content, "timestamp": _now_iso()})


def _extract_lesson_from_chat(messages: list[dict[str, Any]]) -> str | None:
    keywords = [
        "教学目标",
        "学习目标",
        "教学重难点",
        "教学过程",
        "导入",
        "新授",
        "练习",
        "总结",
        "板书",
        "评价",
    ]
    for m in reversed(messages[-40:]):
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if len(text) < 240:
            continue
        hit = any(k in text for k in keywords)
        looks_like_plan = hit or text.count("\n") >= 10 or ("##" in text and "###" in text)
        if looks_like_plan:
            return text
    return None


def _clean_url(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("`") and t.endswith("`") and len(t) >= 2:
        t = t[1:-1].strip()
    if t.startswith('"') and t.endswith('"') and len(t) >= 2:
        t = t[1:-1].strip()
    return t


def _video_queue_to_mappings(storyboard: dict[str, Any]) -> list[dict[str, str]]:
    queue = storyboard.get("video_queue", {})
    q_segs = queue.get("segments", []) if isinstance(queue, dict) else []
    prompt = storyboard.get("video_prompt", {})
    p_segs = prompt.get("segments", []) if isinstance(prompt, dict) else []

    mappings: list[dict[str, str]] = []
    for idx, state in enumerate(q_segs):
        if not isinstance(state, dict):
            continue
        status = str(state.get("status", ""))
        if status not in ("done", "reused"):
            continue
        stage = str(state.get("stage_tag", "")).strip()
        shot = str(state.get("shot_id", "")).strip()
        seg = p_segs[idx] if idx < len(p_segs) and isinstance(p_segs[idx], dict) else {}
        title = stage or str(seg.get("stage_tag", "")).strip() or f"片段{idx + 1}"
        local_path = str(state.get("local_path", "")).strip()
        url = _clean_url(str(state.get("video_url", "")))
        desc = str(seg.get("scene_text", "")).strip()[:160] if isinstance(seg, dict) else ""
        mappings.append(
            {
                "stage": title,
                "video_name": shot or title,
                "video_url": local_path or url,
                "description": desc,
            }
        )
    return mappings


def _queue_summary_markdown(storyboard_id: str, storyboard: dict[str, Any]) -> str:
    queue = storyboard.get("video_queue", {})
    q = queue if isinstance(queue, dict) else {}
    segs = q.get("segments", []) if isinstance(q.get("segments", []), list) else []
    total = len(segs)
    done_count = sum(1 for s in segs if isinstance(s, dict) and str(s.get("status", "")) in ("done", "reused"))
    fail_count = sum(1 for s in segs if isinstance(s, dict) and str(s.get("status", "")) in ("failed", "needs_media_config"))
    status = str(q.get("status", "")) or "unknown"
    combined = str(q.get("combined_local_path", "")).strip()

    lines = [
        f"已关联分镜：{storyboard_id}",
        f"- 队列状态：{status}",
        f"- 进度：{done_count}/{total if total else '?'}",
    ]
    if fail_count:
        lines.append(f"- 异常：{fail_count}")
    if combined:
        lines.append(f"- 合成视频：{combined}")
    lines.append("")
    lines.append("片段概览：")
    if not segs:
        lines.append("- 暂无片段状态（可能还在排队初始化）")
        return "\n".join(lines)

    for i, s in enumerate(segs, start=1):
        if not isinstance(s, dict):
            continue
        shot = str(s.get("shot_id", "")).strip() or f"shot-{i}"
        stage = str(s.get("stage_tag", "")).strip()
        st = str(s.get("status", "")).strip() or "unknown"
        local_path = str(s.get("local_path", "")).strip()
        err = str(s.get("error", "")).strip()
        tail = ""
        if local_path:
            tail = f" → {local_path}"
        elif err and st in ("failed", "needs_media_config"):
            tail = f" → {err[:140]}"
        lines.append(f"- {shot} {f'({stage})' if stage else ''}: {st}{tail}")
    return "\n".join(lines)


def _read_workspace_file(base: Path, rel_path: str) -> str:
    candidate = (base / rel_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {rel_path}")
    return candidate.read_text(encoding="utf-8", errors="ignore")


def _index_search_docs(base: Path, docs: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    results: list[dict[str, Any]] = []
    for doc in docs:
        source_path = str(doc.get("source_path", ""))
        if not source_path:
            continue
        try:
            content = _read_workspace_file(base, source_path)
        except HTTPException:
            continue

        normalized = content.lower()
        if needle:
            hit_count = normalized.count(needle)
            if hit_count <= 0:
                continue
            first = normalized.find(needle)
            start = max(0, first - 180)
            end = min(len(content), first + 420)
            snippet = content[start:end].strip()
            score = float(hit_count)
        else:
            snippet = content[:600].strip()
            score = 0.0

        results.append(
            {
                "mode": "index",
                "doc_id": doc.get("doc_id", ""),
                "source_path": source_path,
                "subject": doc.get("subject", ""),
                "grade": doc.get("grade", ""),
                "score": score,
                "content": snippet,
                "full_content": content,
            }
        )

    results.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return results[: max(1, top_k)]


class Runtime:
    """Holds long-lived API runtime objects."""

    def __init__(self) -> None:
        self.config: Config | None = None
        self.agent: AgentLoop | None = None

    async def ensure(self) -> None:
        if self.agent:
            return
        config_path = os.getenv("NANOBOT_CONFIG")
        if config_path:
            set_config_path(Path(config_path).expanduser().resolve())
        self.config = load_config(get_config_path())
        if self.config.education.enabled and getattr(self.config.education, "auto_import_materials", True):
            materials_dir = str(getattr(self.config.education, "materials_dir", "documents/materials") or "").strip()
            if materials_dir:
                p = Path(materials_dir).expanduser()
                if not p.is_absolute():
                    p = (self.config.workspace_path.resolve() / p).resolve()
                p.mkdir(parents=True, exist_ok=True)

        bus = MessageBus()
        provider = _make_provider(self.config)
        self.agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=self.config.workspace_path,
            model=self.config.agents.defaults.model,
            max_iterations=self.config.agents.defaults.max_tool_iterations,
            context_window_tokens=self.config.agents.defaults.context_window_tokens,
            brave_api_key=self.config.tools.web.search.api_key or None,
            web_proxy=self.config.tools.web.proxy or None,
            exec_config=self.config.tools.exec,
            restrict_to_workspace=self.config.tools.restrict_to_workspace,
            mcp_servers=self.config.tools.mcp_servers,
            channels_config=self.config.channels,
            education_config=self.config.education,
        )


runtime = Runtime()
app = FastAPI(title="nanobot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await runtime.ensure()
    _schedule_global_teacher_profile_refresh()


@app.get("/api/system/info")
async def system_info() -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    media = cfg.education.media
    media_configured = bool(str(media.base_url or "").strip()) and bool(str(media.api_key or "").strip())
    return {
        "workspace": str(cfg.workspace_path),
        "model": cfg.agents.defaults.model,
        "provider": cfg.agents.defaults.provider,
        "education_enabled": cfg.education.enabled,
        "media_configured": media_configured,
    }


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    return cfg.model_dump(by_alias=True)


@app.post("/api/config")
async def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    await runtime.ensure()
    try:
        cfg = Config.model_validate(payload)
        save_config(cfg)
        runtime.config = cfg
        runtime.agent = None
        await runtime.ensure()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/skills")
async def list_skills() -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    loader = SkillsLoader(cfg.workspace_path)
    return {"skills": loader.list_skills(filter_unavailable=False)}


@app.get("/api/skills/{name}")
async def get_skill(name: str) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    loader = SkillsLoader(cfg.workspace_path)
    skill = loader.get_skill_entry(name)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    content = loader.load_skill(name)
    return {
        "name": name,
        "source": skill["source"],
        "path": skill["path"],
        "content": content or "",
    }


@app.put("/api/skills/{name}")
async def update_skill(name: str, req: SkillUpdateRequest) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    loader = SkillsLoader(cfg.workspace_path)
    path = loader.save_skill(name=name, content=req.content, source=req.source)
    return {"status": "ok", "name": name, "path": str(path)}


@app.get("/api/mcp/servers")
async def list_mcp_servers() -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    servers = cfg.tools.mcp_servers
    return {
        "servers": [
            {
                "name": name,
                "type": spec.type,
                "url": spec.url,
                "command": spec.command,
            }
            for name, spec in servers.items()
        ]
    }


@app.get("/api/mcp/config")
async def get_mcp_config() -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    servers = cfg.tools.mcp_servers
    return {
        "servers": {
            name: {
                "type": spec.type,
                "command": spec.command,
                "args": spec.args,
                "env": spec.env,
                "url": spec.url,
                "headers": spec.headers,
                "tool_timeout": spec.tool_timeout,
            }
            for name, spec in servers.items()
        }
    }


@app.put("/api/mcp/config")
async def update_mcp_config(req: MCPConfigUpdateRequest) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    payload = cfg.model_dump(by_alias=True)
    payload.setdefault("tools", {})["mcpServers"] = req.servers
    try:
        next_cfg = Config.model_validate(payload)
        save_config(next_cfg)
        runtime.config = next_cfg
        runtime.agent = None
        await runtime.ensure()
        return {"status": "ok", "servers": list(next_cfg.tools.mcp_servers.keys())}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files")
async def list_files(path: str = ".") -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    base = cfg.workspace_path.resolve()
    target = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")

    entries = []
    for p in sorted(target.iterdir(), key=lambda x: x.name.lower()):
        entries.append({
            "name": p.name,
            "path": str(p.relative_to(base)),
            "is_dir": p.is_dir(),
        })
    return {"entries": entries}


@app.get("/api/files/content")
async def get_file_content(path: str) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    base = cfg.workspace_path.resolve()
    target = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    return {"path": path, "content": target.read_text(encoding="utf-8", errors="ignore")}


@app.put("/api/files/content")
async def update_file_content(path: str, payload: dict[str, str]) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    base = cfg.workspace_path.resolve()
    target = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc

    content = payload.get("content", "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"status": "ok", "path": path}


@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...), target_dir: str = "documents/uploads") -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    base = cfg.workspace_path.resolve()
    output_dir = (base / target_dir).resolve()
    try:
        output_dir.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="target_dir outside workspace") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / file.filename
    data = await file.read()
    output.write_bytes(data)
    return {"status": "ok", "path": str(output.relative_to(base)), "size": len(data)}


@app.post("/api/chat/send", response_model=ChatResponse)
async def chat_send(req: ChatRequest) -> ChatResponse:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")

    session = runtime.agent.sessions.get_or_create(req.session_key)
    raw = (req.message or "").strip()
    cmd = raw.lower()
    if cmd.startswith("/video") or raw.startswith("/视频"):
        before = len(session.messages)
        _append_session_message(session, "user", req.message or "")

        prefix = "/video" if cmd.startswith("/video") else "/视频"
        rest = raw[len(prefix) :].strip()
        head = rest.split(None, 1)[0].lower() if rest else ""
        tail = rest.split(None, 1)[1].strip() if rest and len(rest.split(None, 1)) > 1 else ""

        action = "start"
        if head in ("status", "进度"):
            action = "status"
        elif head in ("export", "导出", "合并"):
            action = "export"
        elif head in ("retry", "重试", "重新"):
            action = "retry"

        last_id = ""
        if isinstance(getattr(session, "metadata", None), dict):
            last_id = str(session.metadata.get("last_storyboard_id", "")).strip()

        if action in ("status", "export", "retry"):
            storyboard_id = tail.strip() or last_id
            if not storyboard_id:
                reply = (
                    "未找到要操作的分镜 ID。\n"
                    "- 先用 /video 生成一个分镜并开始视频任务\n"
                    "- 或者用 /video status sb-xxxxxx 指定分镜 ID"
                )
                _append_session_message(session, "assistant", reply)
                runtime.agent.sessions.save(session)
                session = runtime.agent.sessions.get_or_create(req.session_key)
                delta = session.messages[before:]
                chat_delta = _chat_view_from_session(delta)
                trace = chat_delta[-1].get("traces", []) if chat_delta else []
                return ChatResponse(response=reply, trace=trace)

            storyboard = _load_storyboard(storyboard_id)
            if action == "status":
                reply = _queue_summary_markdown(storyboard_id, storyboard)
            elif action == "retry":
                queue = _start_storyboard_video_queue(
                    storyboard_id,
                    {
                        "style": "educational cinematic",
                        "ratio": "16:9",
                        "duration": 5,
                        "only_selected": True,
                    },
                )
                storyboard = _load_storyboard(storyboard_id)
                reply = "\n".join(
                    [
                        "已重新提交视频队列任务。",
                        "",
                        _queue_summary_markdown(storyboard_id, storyboard),
                        "",
                        "用 /video status 查看进度，用 /video export 输出“教案 + 视频映射”。",
                    ]
                )
            else:
                lesson = str(storyboard.get("lesson_plan", "")).strip()
                if not lesson:
                    lesson = _extract_lesson_from_chat(session.messages) or ""
                mappings = _video_queue_to_mappings(storyboard)
                reply = _render_markdown_export(
                    title="教案与视频映射",
                    lesson_content=lesson or "（未找到教案正文，可将教案粘贴在 /video 后再次生成分镜）",
                    mappings=mappings,
                )

            _append_session_message(session, "assistant", reply)
            profile_key = _teacher_profile_key(req.session_key)
            profile = _update_profile_from_message(profile_key, req.message)
            session.metadata.setdefault("teacher_profile", profile)
            runtime.agent.sessions.save(session)
            _schedule_global_teacher_profile_refresh()

            session = runtime.agent.sessions.get_or_create(req.session_key)
            delta = session.messages[before:]
            chat_delta = _chat_view_from_session(delta)
            trace = chat_delta[-1].get("traces", []) if chat_delta else []
            return ChatResponse(response=reply, trace=trace)

        lesson_override = rest.strip()
        lesson_plan = lesson_override if lesson_override else (_extract_lesson_from_chat(session.messages) or "")
        if not lesson_plan.strip():
            reply = "未在上文找到可用教案。请把教案正文粘贴在 /video 后面，例如：\n\n/video <粘贴教案正文>"
            _append_session_message(session, "assistant", reply)
            runtime.agent.sessions.save(session)
            session = runtime.agent.sessions.get_or_create(req.session_key)
            delta = session.messages[before:]
            chat_delta = _chat_view_from_session(delta)
            trace = chat_delta[-1].get("traces", []) if chat_delta else []
            return ChatResponse(response=reply, trace=trace)

        output = await runtime.agent.tools.execute(
            "lesson_to_video_prompt",
            {
                "lesson_plan": lesson_plan,
                "style": "educational cinematic",
                "duration_seconds": 60,
            },
        )
        try:
            parsed = json.loads(output)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid storyboard generation response: {exc}") from exc
        video_prompt = parsed.get("video_prompt", {}) if isinstance(parsed, dict) else {}
        storyboard_id = f"sb-{uuid4().hex[:12]}"
        payload = {
            "id": storyboard_id,
            "confirmed": True,
            "video_prompt": video_prompt,
            "lesson_plan": lesson_plan,
            "lesson_quality": _check_lesson_text_quality(lesson_plan),
        }
        _save_storyboard(storyboard_id, payload)
        _start_storyboard_video_queue(
            storyboard_id,
            {
                "style": "educational cinematic",
                "ratio": "16:9",
                "duration": 5,
                "only_selected": True,
            },
        )

        session.metadata["last_storyboard_id"] = storyboard_id
        reply = "\n".join(
            [
                "已在对话内创建分镜并提交视频任务。",
                f"- 分镜 ID：{storyboard_id}",
                "",
                "下一步：",
                "- /video status 查看进度",
                "- /video export 输出“教案 + 教学阶段与视频映射”",
            ]
        )
        _append_session_message(session, "assistant", reply)
        profile_key = _teacher_profile_key(req.session_key)
        profile = _update_profile_from_message(profile_key, req.message)
        session.metadata.setdefault("teacher_profile", profile)
        runtime.agent.sessions.save(session)
        _schedule_global_teacher_profile_refresh()

        session = runtime.agent.sessions.get_or_create(req.session_key)
        delta = session.messages[before:]
        chat_delta = _chat_view_from_session(delta)
        trace = chat_delta[-1].get("traces", []) if chat_delta else []
        return ChatResponse(response=reply, trace=trace)

    before = len(session.messages)

    response = await runtime.agent.process_direct(
        req.message,
        session_key=req.session_key,
        channel="web",
        chat_id=req.session_key,
    )

    profile_key = _teacher_profile_key(req.session_key)
    profile = _update_profile_from_message(profile_key, req.message)
    session.metadata.setdefault("teacher_profile", profile)
    runtime.agent.sessions.save(session)
    _schedule_global_teacher_profile_refresh()

    session = runtime.agent.sessions.get_or_create(req.session_key)
    delta = session.messages[before:]
    chat_delta = _chat_view_from_session(delta)
    trace = chat_delta[-1].get("traces", []) if chat_delta else []
    return ChatResponse(response=response, trace=trace)


@app.get("/api/chat/history")
async def chat_history(session_key: str = "web:console") -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")

    session = runtime.agent.sessions.get_or_create(session_key)
    return {
        "status": "ok",
        "session_key": session_key,
        "messages": _chat_view_from_session(session.messages),
    }


@app.post("/api/chat/clear")
async def clear_chat(session_key: str = "web:console") -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")
    session = runtime.agent.sessions.get_or_create(session_key)
    session.clear()
    runtime.agent.sessions.save(session)
    runtime.agent.sessions.invalidate(session.key)
    return {"status": "ok", "session_key": session_key}


@app.get("/api/teacher/profile/questionnaire")
async def teacher_profile_questionnaire(session_key: str = "web:default") -> dict[str, Any]:
    await runtime.ensure()
    profile = _get_teacher_profile(session_key)
    return {
        "status": "ok",
        "session_key": session_key,
        "missing_fields": [],
        "profile": profile,
        "questions": {},
        "message": "画像由 Agent 基于对话自动提取，当前接口用于查看与微调。",
    }


@app.get("/api/teacher/profile")
async def get_teacher_profile(session_key: str = "web:default") -> dict[str, Any]:
    await runtime.ensure()
    return {"status": "ok", "profile": _get_teacher_profile(session_key)}


@app.put("/api/teacher/profile")
async def update_teacher_profile(req: TeacherProfileUpdateRequest) -> dict[str, Any]:
    await runtime.ensure()
    payload = req.model_dump()
    session_key = payload.pop("session_key")
    persona_payload = payload.pop("persona", {})
    cleaned = {k: v for k, v in payload.items() if isinstance(v, str) and v.strip()}
    if isinstance(persona_payload, dict) and persona_payload:
        cleaned["persona"] = persona_payload
    profile = _put_teacher_profile(session_key, cleaned)
    if runtime.agent:
        session = runtime.agent.sessions.get_or_create(session_key)
        session.metadata["teacher_profile"] = profile
        runtime.agent.sessions.save(session)
    return {"status": "ok", "profile": profile}


@app.get("/api/documents")
async def list_documents() -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")
    output = await runtime.agent.tools.execute("document_list", {})
    if isinstance(output, str) and output.startswith("Error"):
        raise HTTPException(status_code=400, detail=output)
    try:
        return json.loads(output)
    except Exception:
        return {"raw": output}


@app.post("/api/documents/import")
async def import_document(req: DocumentImportRequest) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")

    output = await runtime.agent.tools.execute(
        "document_import",
        {
            "path": req.path,
            "subject": req.subject,
            "grade": req.grade,
        },
    )
    if isinstance(output, str) and output.startswith("Error"):
        raise HTTPException(status_code=400, detail=output)
    try:
        return json.loads(output)
    except Exception:
        return {"raw": output}


@app.post("/api/documents/import-dir")
async def import_document_dir(req: DocumentImportDirRequest) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")

    output = await runtime.agent.tools.execute(
        "document_import_dir",
        {
            "path": req.path,
            "recursive": req.recursive,
            "max_files": req.max_files,
            "subject": req.subject,
            "grade": req.grade,
        },
    )
    if isinstance(output, str) and output.startswith("Error"):
        raise HTTPException(status_code=400, detail=output)
    try:
        return json.loads(output)
    except Exception:
        return {"raw": output}


@app.post("/api/documents/query")
async def query_documents(req: DocumentQueryRequest) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent or not runtime.config:
        raise HTTPException(status_code=500, detail="agent not ready")

    mode = (req.mode or "vector").strip().lower()
    if mode == "vector":
        output = await runtime.agent.tools.execute(
            "document_search",
            {
                "query": req.query,
                "top_k": req.top_k,
                "subject": req.subject,
                "grade": req.grade,
            },
        )
        if isinstance(output, str) and output.startswith("Error"):
            raise HTTPException(status_code=400, detail=output)
        try:
            result = json.loads(output)
        except Exception:
            result = {"raw": output}
        return {
            "status": "ok",
            "mode": "vector",
            "query": req.query,
            "results": result.get("hits", []),
        }

    if mode == "index":
        raw_docs = await runtime.agent.tools.execute("document_list", {})
        if isinstance(raw_docs, str) and raw_docs.startswith("Error"):
            raise HTTPException(status_code=400, detail=raw_docs)
        try:
            parsed = json.loads(raw_docs)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"failed to parse document list: {exc}") from exc
        docs = parsed.get("documents", []) if isinstance(parsed, dict) else []
        results = _index_search_docs(
            base=runtime.config.workspace_path.resolve(),
            docs=docs,
            query=req.query,
            top_k=req.top_k,
        )
        return {
            "status": "ok",
            "mode": "index",
            "query": req.query,
            "results": results,
        }

    raise HTTPException(status_code=400, detail="mode must be 'vector' or 'index'")


@app.post("/api/lessons/generate-advanced")
async def generate_advanced_lesson(req: AdvancedLessonPlanRequest) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")

    profile = _get_teacher_profile(req.session_key)
    persona_summary = _summarize_teacher_persona(profile)
    objectives = [x.strip() for x in req.learning_objectives if str(x).strip()]
    if not objectives:
        objectives = [
            "学生能够准确说出本节课关键概念",
            "学生能够完成基于本课知识的应用任务",
        ]

    selected_activities = [x.strip() for x in req.selected_activities if str(x).strip()]
    if not selected_activities:
        selected_activities = get_mode_activity_pack(req.teaching_mode)[:3]

    output = await runtime.agent.tools.execute(
        "lesson_plan_generate",
        {
            "subject": req.subject,
            "grade": req.grade,
            "topic": req.topic,
            "duration_minutes": req.duration_minutes,
            "teaching_objectives": objectives,
            "prior_knowledge": req.prior_knowledge,
            "learner_misconceptions": req.misconceptions,
            "learner_interests": req.interests,
            "key_points": req.key_points,
            "difficult_points": req.difficulties,
            "teaching_mode": req.teaching_mode,
            "selected_activities": selected_activities,
            "teacher_profile": profile,
            "needs_quiz": req.needs_quiz,
            "needs_rubric": req.needs_rubric,
            "needs_differentiation": req.needs_differentiation,
            "references": req.references,
            "language": req.language,
            "output_format": "json",
        },
    )

    if isinstance(output, str) and output.startswith("Error"):
        raise HTTPException(status_code=400, detail=output)

    try:
        parsed = json.loads(output)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid lesson generation response: {exc}") from exc

    lesson_plan = parsed.get("lesson_plan", {}) if isinstance(parsed, dict) else {}
    lesson_markdown = parsed.get("lesson_markdown", "") if isinstance(parsed, dict) else ""
    generation_prompt = parsed.get("generation_prompt", "") if isinstance(parsed, dict) else ""

    report = validate_lesson_plan(
        plan=lesson_plan if isinstance(lesson_plan, dict) else {},
        duration_minutes=req.duration_minutes,
        objectives=objectives,
        needs_quiz=req.needs_quiz,
        needs_rubric=req.needs_rubric,
        needs_differentiation=req.needs_differentiation,
    )
    result = report.to_dict()

    return {
        "status": "ok",
        "lesson_plan": lesson_plan,
        "lesson_markdown": lesson_markdown,
        "generation_prompt": generation_prompt,
        "teacher_persona_summary": persona_summary,
        "validation_report": result,
        "validation_passed": bool(result.get("passed", False)),
        "suggestions": [x["message"] for x in result.get("issues", [])[:8]],
    }


@app.get("/api/templates/lessons")
async def get_lesson_templates(
    subject: str = "",
    grade: str = "",
    teaching_mode: str = "",
    topic: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    await runtime.ensure()
    rows = list_lesson_templates(
        templates_file=_lesson_templates_file(),
        subject=subject,
        grade=grade,
        teaching_mode=teaching_mode,
        topic=topic,
        limit=limit,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "filters": {
            "subject": subject,
            "grade": grade,
            "teaching_mode": teaching_mode,
            "topic": topic,
            "limit": limit,
        },
        "templates": rows,
    }


@app.get("/api/templates/activities")
async def get_activity_packs(
    subject: str = "",
    teaching_mode: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    await runtime.ensure()
    rows = list_activity_packs(
        packs_file=_activity_packs_file(),
        teaching_mode=teaching_mode,
        subject=subject,
        limit=limit,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "filters": {
            "subject": subject,
            "teaching_mode": teaching_mode,
            "limit": limit,
        },
        "activities": rows,
    }


@app.post("/api/templates/lessons")
async def create_lesson_template(req: LessonTemplateCreateRequest) -> dict[str, Any]:
    await runtime.ensure()
    payload = req.model_dump()
    payload["id"] = payload.get("id") or f"tpl-{uuid4().hex[:10]}"
    payload["created_at"] = _now_iso()
    item = _append_jsonl(_lesson_templates_file(), payload)
    return {"status": "ok", "template": item}


@app.post("/api/templates/activities")
async def create_activity_pack(req: ActivityPackCreateRequest) -> dict[str, Any]:
    await runtime.ensure()
    payload = req.model_dump()
    payload["id"] = payload.get("id") or f"act-{uuid4().hex[:10]}"
    payload["created_at"] = _now_iso()
    item = _append_jsonl(_activity_packs_file(), payload)
    return {"status": "ok", "activity": item}


@app.post("/api/storyboards")
async def create_storyboard(req: StoryboardCreateRequest) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")
    output = await runtime.agent.tools.execute(
        "lesson_to_video_prompt",
        {
            "lesson_plan": req.lesson_plan,
            "style": req.style,
            "duration_seconds": req.duration_seconds,
        },
    )
    try:
        parsed = json.loads(output)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid storyboard generation response: {exc}") from exc
    video_prompt = parsed.get("video_prompt", {}) if isinstance(parsed, dict) else {}
    storyboard_id = f"sb-{uuid4().hex[:12]}"
    payload = {
        "id": storyboard_id,
        "confirmed": False,
        "video_prompt": video_prompt,
        "lesson_plan": req.lesson_plan,
        "lesson_quality": _check_lesson_text_quality(req.lesson_plan),
    }
    _save_storyboard(storyboard_id, payload)
    return {"status": "ok", "storyboard": payload}


@app.get("/api/storyboards/{storyboard_id}")
async def get_storyboard(storyboard_id: str) -> dict[str, Any]:
    await runtime.ensure()
    return {"status": "ok", "storyboard": _load_storyboard(storyboard_id)}


@app.put("/api/storyboards/{storyboard_id}/segments/{segment_num}")
async def edit_storyboard_segment(
    storyboard_id: str,
    segment_num: int,
    req: StoryboardSegmentUpdateRequest,
) -> dict[str, Any]:
    await runtime.ensure()
    storyboard = _load_storyboard(storyboard_id)
    prompt = storyboard.get("video_prompt", {})
    segments = prompt.get("segments", []) if isinstance(prompt, dict) else []
    idx = max(1, segment_num) - 1
    if idx >= len(segments):
        raise HTTPException(status_code=404, detail="segment not found")
    update_data = req.model_dump(exclude_none=True)
    segments[idx].update(update_data)
    if "duration_sec" in update_data:
        segments[idx]["duration"] = update_data["duration_sec"]
    storyboard["confirmed"] = False
    storyboard["video_prompt"] = prompt
    _save_storyboard(storyboard_id, storyboard)
    return {"status": "ok", "storyboard": storyboard}


@app.get("/api/storyboards/{storyboard_id}/segments/{segment_num}/reuse-candidates")
async def storyboard_segment_reuse_candidates(
    storyboard_id: str,
    segment_num: int,
    top_k: int = 8,
    include_materials: bool = True,
) -> dict[str, Any]:
    await runtime.ensure()
    storyboard = _load_storyboard(storyboard_id)
    prompt = storyboard.get("video_prompt", {})
    segments = prompt.get("segments", []) if isinstance(prompt, dict) else []
    idx = max(1, segment_num) - 1
    if idx >= len(segments) or not isinstance(segments[idx], dict):
        raise HTTPException(status_code=404, detail="segment not found")
    seg = segments[idx]
    tokens = _segment_tokens(seg)
    results: list[dict[str, Any]] = []

    for it in _read_video_library():
        name = str(it.get("name", ""))
        desc = str(it.get("description", ""))
        tags = " ".join(str(t) for t in (it.get("tags", []) if isinstance(it.get("tags", []), list) else []))
        hay = f"{name} {desc} {tags}"
        score = _score_tokens(tokens, hay) if tokens else 0
        if score > 0:
            results.append({"score": score, "source": "library", "video": it})

    if include_materials and tokens:
        base = _workspace_base()
        for p in _material_video_files(max_files=240):
            rel = ""
            try:
                rel = str(p.resolve().relative_to(base))
            except Exception:
                rel = str(p)
            hay = f"{p.name} {p.parent.name} {rel}"
            score = _score_tokens(tokens, hay)
            if score > 0:
                results.append(
                    {
                        "score": score,
                        "source": "materials",
                        "video": {
                            "name": p.stem,
                            "description": f"materials: {rel}",
                            "task_id": "",
                            "video_url": "",
                            "tags": ["materials"],
                            "source": "materials",
                            "local_path": rel,
                        },
                    }
                )

    results.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    return {
        "status": "ok",
        "storyboard_id": storyboard_id,
        "segment_num": segment_num,
        "tokens": tokens,
        "candidates": results[: max(1, min(50, top_k))],
    }


@app.post("/api/storyboards/{storyboard_id}/confirm")
async def confirm_storyboard(storyboard_id: str) -> dict[str, Any]:
    await runtime.ensure()
    storyboard = _load_storyboard(storyboard_id)
    storyboard["confirmed"] = True
    _save_storyboard(storyboard_id, storyboard)
    return {"status": "ok", "storyboard": storyboard}


@app.post("/api/storyboards/{storyboard_id}/generate-video")
async def generate_video_from_storyboard(
    storyboard_id: str,
    req: StoryboardGenerateVideoRequest,
) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")
    storyboard = _load_storyboard(storyboard_id)
    prompt = storyboard.get("video_prompt", {})
    segments = prompt.get("segments", []) if isinstance(prompt, dict) else []
    if req.only_selected:
        segments = [x for x in segments if isinstance(x, dict) and bool(x.get("selected", True))]
    else:
        segments = [x for x in segments if isinstance(x, dict)]
    if not segments:
        raise HTTPException(status_code=400, detail="no selected segments to generate")
    queue = _start_storyboard_video_queue(storyboard_id, req.model_dump())
    return {"status": "ok", "storyboard_id": storyboard_id, "video_queue": queue}


@app.get("/api/videos")
async def list_videos() -> dict[str, Any]:
    await runtime.ensure()
    items = _read_video_library()
    items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return {"status": "ok", "videos": items}


@app.post("/api/videos")
async def save_video(req: VideoLibrarySaveRequest) -> dict[str, Any]:
    await runtime.ensure()
    item = _append_video_library(
        {
            "name": req.name,
            "description": req.description,
            "task_id": req.task_id,
            "video_url": req.video_url,
            "subject": req.subject,
            "grade": req.grade,
            "tags": req.tags,
            "source": "generated",
        }
    )
    return {"status": "ok", "video": item}


@app.post("/api/videos/import-local")
async def import_local_video(req: VideoImportLocalRequest) -> dict[str, Any]:
    await runtime.ensure()
    base = _workspace_base()
    src = (base / req.path).resolve() if not Path(req.path).is_absolute() else Path(req.path).resolve()
    try:
        src.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail="video file not found")

    storage = base / "videos" / "assets"
    storage.mkdir(parents=True, exist_ok=True)
    dest = storage / f"{uuid4().hex[:10]}_{src.name}"
    shutil.copyfile(src, dest)
    item = _append_video_library(
        {
            "name": req.name,
            "description": req.description,
            "subject": req.subject,
            "grade": req.grade,
            "tags": req.tags,
            "source": "local",
            "local_path": str(dest.relative_to(base)),
            "video_url": "",
        }
    )
    return {"status": "ok", "video": item}


@app.get("/api/videos/recommend")
async def recommend_videos(query: str, top_k: int = 5) -> dict[str, Any]:
    await runtime.ensure()
    needle = query.strip().lower()
    if not needle:
        return {"status": "ok", "results": []}

    candidates = []
    for item in _read_video_library():
        name = str(item.get("name", "")).lower()
        desc = str(item.get("description", "")).lower()
        tags = " ".join([str(t).lower() for t in item.get("tags", [])])
        hay = f"{name} {desc} {tags}"
        score = hay.count(needle)
        if score <= 0:
            # token overlap fallback
            tokens = [t for t in re.split(r"\s+", needle) if t]
            score = sum(1 for t in tokens if t in hay)
        if score > 0:
            candidates.append({"score": score, "video": item})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return {"status": "ok", "results": candidates[: max(1, top_k)]}


@app.post("/api/export/lesson-video")
async def export_lesson_video(req: ExportLessonVideoRequest) -> dict[str, Any]:
    await runtime.ensure()
    base = _workspace_base()
    exports = base / "videos" / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    markdown = _render_markdown_export(req.title, req.lesson_content, req.mappings)
    export_id = f"exp-{uuid4().hex[:10]}"
    md_path = exports / f"{export_id}.md"
    md_path.write_text(markdown, encoding="utf-8")

    fmt = req.format.strip().lower()
    if fmt in ("markdown", "md"):
        relative = str(md_path.relative_to(base))
        return {
            "status": "ok",
            "format": "markdown",
            "path": relative,
            "download_url": f"/api/files/download?path={relative}",
            "available_formats": ["markdown", "docx", "pdf"],
        }

    if fmt in ("docx", "pdf"):
        pandoc = shutil.which("pandoc")
        if not pandoc:
            relative = str(md_path.relative_to(base))
            return {
                "status": "degraded",
                "format": "markdown",
                "path": relative,
                "download_url": f"/api/files/download?path={relative}",
                "detail": "pandoc not installed; fallback to markdown",
                "available_formats": ["markdown"],
            }
        out_path = exports / f"{export_id}.{fmt}"
        try:
            subprocess.run([pandoc, str(md_path), "-o", str(out_path)], check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
            raise HTTPException(status_code=400, detail=f"pandoc conversion failed: {err}") from exc
        relative = str(out_path.relative_to(base))
        return {
            "status": "ok",
            "format": fmt,
            "path": relative,
            "download_url": f"/api/files/download?path={relative}",
            "available_formats": ["markdown", "docx", "pdf"],
        }

    raise HTTPException(status_code=400, detail="format must be markdown|docx|pdf")


@app.get("/api/files/download")
async def download_file(path: str):
    await runtime.ensure()
    cfg = runtime.config
    assert cfg is not None
    base = cfg.workspace_path.resolve()
    target = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=target, filename=target.name, media_type="application/octet-stream")


@app.get("/api/media/tasks/{task_id}")
async def query_media_task(task_id: str, wait: bool = False) -> dict[str, Any]:
    await runtime.ensure()
    if not runtime.agent:
        raise HTTPException(status_code=500, detail="agent not ready")
    output = await runtime.agent.tools.execute(
        "media_query_task", {"task_id": task_id, "wait": wait}
    )
    try:
        return json.loads(output)
    except Exception:
        return {"raw": output}


@app.get("/api/media/ark/tasks/{task_id}")
async def query_ark_media_task(task_id: str) -> dict[str, Any]:
    await runtime.ensure()
    cfg = runtime.config
    if not cfg:
        raise HTTPException(status_code=500, detail="runtime config missing")
    base_url = cfg.education.media.base_url.rstrip("/")
    api_key = cfg.education.media.api_key
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="education.media base_url/api_key not configured")

    endpoint = f"{base_url}/api/v3/contents/generations/tasks/{task_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(endpoint, headers=headers)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])

    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    return {"status": "ok", "task_id": task_id, "result": payload}


def main() -> None:
    host = os.getenv("NANOBOT_API_HOST", "127.0.0.1")
    port = int(os.getenv("NANOBOT_API_PORT", "8000"))
    uvicorn.run("nanobot.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
