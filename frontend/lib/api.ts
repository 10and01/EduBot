const API_BASE = process.env.NEXT_PUBLIC_NANOBOT_API_BASE || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API ${path} failed: ${resp.status} ${text}`);
  }
  return resp.json() as Promise<T>;
}

export async function getSystemInfo() {
  return request<{ workspace: string; model: string; provider: string; education_enabled: boolean; media_configured?: boolean }>(
    "/api/system/info"
  );
}

export async function listSkills() {
  return request<{ skills: Array<{ name: string; path: string; source: string }> }>("/api/skills");
}

export async function getSkill(name: string) {
  return request<{ name: string; source: string; path: string; content: string }>(
    `/api/skills/${encodeURIComponent(name)}`
  );
}

export async function updateSkill(name: string, content: string, source = "auto") {
  return request<{ status: string; name: string; path: string }>(
    `/api/skills/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      body: JSON.stringify({ content, source }),
    }
  );
}

export async function listMcpServers() {
  return request<{
    servers: Array<{ name: string; type: string; url?: string; command?: string }>;
  }>("/api/mcp/servers");
}

export async function getMcpConfig() {
  return request<{ servers: Record<string, unknown> }>("/api/mcp/config");
}

export async function updateMcpConfig(servers: Record<string, unknown>) {
  return request<{ status: string; servers: string[] }>("/api/mcp/config", {
    method: "PUT",
    body: JSON.stringify({ servers }),
  });
}

export async function sendChat(message: string, sessionKey: string) {
  return request<{ response: string; trace?: Array<{ kind: string; emoji: string; title: string; content: string }> }>("/api/chat/send", {
    method: "POST",
    body: JSON.stringify({ message, session_key: sessionKey }),
  });
}

export async function getChatHistory(sessionKey: string) {
  return request<{
    status: string;
    session_key: string;
    messages: Array<{
      role: "user" | "assistant";
      content: string;
      timestamp?: string;
      traces?: Array<{ kind: string; emoji: string; title: string; content: string }>;
    }>;
  }>(`/api/chat/history?session_key=${encodeURIComponent(sessionKey)}`);
}

export async function clearChatHistory(sessionKey: string) {
  return request<{ status: string; session_key: string }>(
    `/api/chat/clear?session_key=${encodeURIComponent(sessionKey)}`,
    { method: "POST" }
  );
}

export async function getConfig() {
  return request<Record<string, unknown>>("/api/config");
}

export async function updateConfig(data: Record<string, unknown>) {
  return request<{ status: string }>("/api/config", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listFiles(path = ".") {
  return request<{ entries: Array<{ name: string; path: string; is_dir: boolean }> }>(`/api/files?path=${encodeURIComponent(path)}`);
}

export async function readFile(path: string) {
  return request<{ path: string; content: string }>(`/api/files/content?path=${encodeURIComponent(path)}`);
}

export async function writeFile(path: string, content: string) {
  return request<{ status: string; path: string }>(`/api/files/content?path=${encodeURIComponent(path)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function listDocuments() {
  return request<Record<string, unknown>>("/api/documents");
}

export async function importDocument(path: string, subject = "", grade = "") {
  return request<Record<string, unknown>>("/api/documents/import", {
    method: "POST",
    body: JSON.stringify({ path, subject, grade }),
  });
}

export async function queryDocuments(
  query: string,
  mode: "vector" | "index" = "vector",
  topK = 5,
  subject = "",
  grade = ""
) {
  return request<{
    status: string;
    mode: "vector" | "index";
    query: string;
    results: Array<Record<string, unknown>>;
  }>("/api/documents/query", {
    method: "POST",
    body: JSON.stringify({ query, mode, top_k: topK, subject, grade }),
  });
}

export async function uploadFile(file: File, targetDir = "documents/uploads") {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(
    `${API_BASE}/api/files/upload?target_dir=${encodeURIComponent(targetDir)}`,
    { method: "POST", body: form, cache: "no-store" }
  );
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`uploadFile failed: ${resp.status} ${text}`);
  }
  return resp.json() as Promise<{ status: string; path: string; size: number }>;
}

export async function queryMediaTask(taskId: string, wait = false) {
  return request<Record<string, unknown>>(
    `/api/media/tasks/${encodeURIComponent(taskId)}?wait=${wait}`
  );
}

export async function queryArkMediaTask(taskId: string) {
  return request<Record<string, unknown>>(
    `/api/media/ark/tasks/${encodeURIComponent(taskId)}`
  );
}

export async function getTeacherProfile(sessionKey: string) {
  return request<{ status: string; profile: Record<string, unknown> }>(
    `/api/teacher/profile?session_key=${encodeURIComponent(sessionKey)}`
  );
}

export async function getTeacherQuestionnaire(sessionKey: string) {
  return request<{ status: string; missing_fields: string[]; profile: Record<string, unknown>; questions: Record<string, string> }>(
    `/api/teacher/profile/questionnaire?session_key=${encodeURIComponent(sessionKey)}`
  );
}

export async function updateTeacherProfile(payload: Record<string, unknown>) {
  return request<{ status: string; profile: Record<string, unknown> }>("/api/teacher/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function createStoryboard(payload: {
  lesson_plan: string;
  style?: string;
  duration_seconds?: number;
}) {
  return request<{ status: string; storyboard: Record<string, unknown> }>("/api/storyboards", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getStoryboard(storyboardId: string) {
  return request<{ status: string; storyboard: Record<string, unknown> }>(
    `/api/storyboards/${encodeURIComponent(storyboardId)}`
  );
}

export async function editStoryboardSegment(storyboardId: string, segmentNum: number, payload: Record<string, unknown>) {
  return request<{ status: string; storyboard: Record<string, unknown> }>(
    `/api/storyboards/${encodeURIComponent(storyboardId)}/segments/${segmentNum}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    }
  );
}

export async function confirmStoryboard(storyboardId: string) {
  return request<{ status: string; storyboard: Record<string, unknown> }>(
    `/api/storyboards/${encodeURIComponent(storyboardId)}/confirm`,
    { method: "POST" }
  );
}

export async function generateVideoFromStoryboard(storyboardId: string, payload: Record<string, unknown>) {
  return request<{ status: string; storyboard_id: string; video_queue: Record<string, unknown> }>(
    `/api/storyboards/${encodeURIComponent(storyboardId)}/generate-video`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function listVideos() {
  return request<{ status: string; videos: Array<Record<string, unknown>> }>("/api/videos");
}

export async function saveVideo(payload: Record<string, unknown>) {
  return request<{ status: string; video: Record<string, unknown> }>("/api/videos", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importLocalVideo(payload: Record<string, unknown>) {
  return request<{ status: string; video: Record<string, unknown> }>("/api/videos/import-local", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function recommendVideos(query: string, topK = 5) {
  return request<{ status: string; results: Array<Record<string, unknown>> }>(
    `/api/videos/recommend?query=${encodeURIComponent(query)}&top_k=${topK}`
  );
}

export async function exportLessonVideo(payload: Record<string, unknown>) {
  return request<{
    status: string;
    format: string;
    path: string;
    download_url?: string;
    detail?: string;
    available_formats?: string[];
  }>("/api/export/lesson-video", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateAdvancedLesson(payload: {
  session_key?: string;
  subject: string;
  grade: string;
  topic: string;
  duration_minutes: number;
  learning_objectives?: string[];
  prior_knowledge?: string[];
  misconceptions?: string[];
  interests?: string[];
  key_points?: string[];
  difficulties?: string[];
  teaching_mode?: string;
  selected_activities?: string[];
  needs_quiz?: boolean;
  needs_rubric?: boolean;
  needs_differentiation?: boolean;
  references?: string[];
  language?: "zh" | "en";
}) {
  return request<{
    status: string;
    lesson_plan: Record<string, unknown>;
    lesson_markdown: string;
    generation_prompt: string;
    teacher_persona_summary?: string;
    validation_report: Record<string, unknown>;
    validation_passed: boolean;
    suggestions: string[];
  }>("/api/lessons/generate-advanced", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listLessonTemplates(params?: {
  subject?: string;
  grade?: string;
  teaching_mode?: string;
  topic?: string;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.subject) q.set("subject", params.subject);
  if (params?.grade) q.set("grade", params.grade);
  if (params?.teaching_mode) q.set("teaching_mode", params.teaching_mode);
  if (params?.topic) q.set("topic", params.topic);
  if (params?.limit) q.set("limit", String(params.limit));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return request<{ status: string; count: number; templates: Array<Record<string, unknown>> }>(
    `/api/templates/lessons${suffix}`
  );
}

export async function listActivityPacks(params?: {
  subject?: string;
  teaching_mode?: string;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.subject) q.set("subject", params.subject);
  if (params?.teaching_mode) q.set("teaching_mode", params.teaching_mode);
  if (params?.limit) q.set("limit", String(params.limit));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return request<{ status: string; count: number; activities: Array<Record<string, unknown>> }>(
    `/api/templates/activities${suffix}`
  );
}

export async function createLessonTemplate(payload: Record<string, unknown>) {
  return request<{ status: string; template: Record<string, unknown> }>("/api/templates/lessons", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createActivityPack(payload: Record<string, unknown>) {
  return request<{ status: string; activity: Record<string, unknown> }>("/api/templates/activities", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
