---
name: video-prompt
description: Convert lesson plans into storyboard prompts and call media APIs.
metadata: {"nanobot":{"emoji":"🎬"}}
---

# Video Prompt

Use this skill when users ask to produce video/image prompts from a lesson plan.

## Workflow

1. Call `lesson_to_video_prompt` with lesson text and style.
2. If user requests asset generation, call `media_generate`:
   - `media_type=image` for cover/slides
   - `media_type=video` for short explainer clips

## Prompt Quality

- Include visual scene, camera movement, and narration goals.
- Keep segment timing explicit.
- Use one pedagogical objective per segment to avoid overloaded scenes.
