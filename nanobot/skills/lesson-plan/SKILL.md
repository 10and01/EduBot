---
name: lesson-plan
description: Generate lesson plans in a fixed structure for classroom design.
metadata: {"nanobot":{"emoji":"📚"}}
---

# Lesson Plan

Use this skill when the user asks for classroom teaching plans, syllabus-aligned sessions, or structured lesson outputs.

## Workflow

1. Start with teacher profiling: collect/confirm subject, grade, teaching style, class duration, and assessment preference.
2. If local materials exist, call `document_search` first.
3. Call `lesson_plan_generate` with `subject`, `grade`, `topic`, and `duration_minutes`.
4. If user needs video, call `lesson_to_video_prompt` to produce storyboard segments.
5. Present storyboard for user editing/selection and confirm before any video generation.
6. If local videos can cover similar content, recommend reuse first and wait for user confirmation.
7. Return output in the requested format (`markdown` by default).

## Required Structure

The lesson plan should always include:
- learning objectives
- knowledge decomposition
- learner analysis
- key points/challenges
- misconceptions and correction strategy
- teaching process with time split
- teacher explanation script
- differentiated activities
- assessment and homework
- assessment rubric
- board plan/resources

## Quality Rules

- Keep language age-appropriate for the selected grade.
- Prefer measurable objectives (observable actions).
- Include references when retrieval evidence is available.
- Prefer actionable classroom phrasing over generic descriptions.
