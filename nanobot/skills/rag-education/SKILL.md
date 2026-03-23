---
name: rag-education
description: Retrieve local teaching materials before generating lesson plans.
metadata: {"nanobot":{"emoji":"🧠"}}
---

# RAG Education

Use this skill to ground responses in imported local files.

## Workflow

1. Use `document_list` to inspect indexed material.
2. Use `document_search` with focused queries (topic, objective, misconceptions).
3. Summarize retrieved evidence before composing final answer.
4. For lesson plan requests, pass concise references to `lesson_plan_generate`.

## Query Tips

- Include subject + grade in the search query.
- Run two searches when needed:
  - concept explanation
  - activity/assessment examples

## Safety

- If no material is found, clearly state retrieval is empty.
- Do not fabricate citations.
