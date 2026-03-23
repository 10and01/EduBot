"""JSONL-based lesson template and activity pack recommender."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_jsonl(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def list_lesson_templates(
    templates_file: Path,
    subject: str = "",
    grade: str = "",
    teaching_mode: str = "",
    topic: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = _read_jsonl(templates_file)
    subject = subject.strip().lower()
    grade = grade.strip().lower()
    teaching_mode = teaching_mode.strip().lower()
    topic = topic.strip().lower()

    filtered: list[dict[str, Any]] = []
    for item in rows:
        if subject and subject not in str(item.get("subject", "")).lower():
            continue
        if grade and grade not in str(item.get("grade", "")).lower():
            continue
        if teaching_mode and teaching_mode not in str(item.get("teaching_mode", "")).lower():
            continue
        if topic and topic not in str(item.get("topic", "")).lower() and topic not in str(item.get("content", "")).lower():
            continue
        filtered.append(item)
    return filtered[: max(1, limit)]


def list_activity_packs(
    packs_file: Path,
    teaching_mode: str = "",
    subject: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = _read_jsonl(packs_file)
    mode = teaching_mode.strip().lower()
    subj = subject.strip().lower()

    filtered: list[dict[str, Any]] = []
    for item in rows:
        if mode and mode not in str(item.get("teaching_mode", "")).lower():
            continue
        if subj and subj not in str(item.get("subject", "")).lower() and str(item.get("subject", "")).lower() not in ("", "通用"):
            continue
        filtered.append(item)
    return filtered[: max(1, limit)]
