"use client";

import {
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Input,
  Layout,
  List,
  Segmented,
  Select,
  Row,
  Space,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile, UploadProps } from "antd";
import type { ChangeEvent, KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEffect, useRef, useState } from "react";
import {
  clearChatHistory,
  confirmStoryboard,
  createStoryboard,
  editStoryboardSegment,
  exportLessonVideo,
  generateAdvancedLesson,
  getConfig,
  getTeacherQuestionnaire,
  getMcpConfig,
  getTeacherProfile,
  getStoryboard,
  getSkill,
  getChatHistory,
  getSystemInfo,
  generateVideoFromStoryboard,
  importLocalVideo,
  listActivityPacks,
  listLessonTemplates,
  listVideos,
  recommendVideos,
  queryArkMediaTask,
  queryDocuments,
  listDocuments,
  listFiles,
  listMcpServers,
  listSkills,
  readFile,
  sendChat,
  updateTeacherProfile,
  updateMcpConfig,
  importDocument,
  updateSkill,
  updateConfig,
  uploadFile,
  writeFile,
} from "../lib/api";

const { Sider, Content } = Layout;
const { Paragraph, Text, Title } = Typography;

type ChatMessage = { role: "user" | "assistant"; content: string };
type ChatTrace = { kind: string; emoji: string; title: string; content: string };
type UIChatMessage = ChatMessage & { traces?: ChatTrace[]; timestamp?: string };
type SkillItem = { name: string; path: string; source: string };
type MCPItem = { name: string; type: string; url?: string; command?: string };
type NavKey = "chat" | "lesson" | "config" | "skills" | "files" | "docs" | "videos";
type ChatSession = { key: string; title: string; createdAt: number };

const NAV_ITEMS: Array<{ key: NavKey; icon: string; label: string }> = [
  { key: "chat", icon: "💬", label: "对话" },
  { key: "lesson", icon: "🧠", label: "高级教案向导" },
  { key: "config", icon: "⚙️", label: "API 配置" },
  { key: "skills", icon: "🧩", label: "Skills / MCP" },
  { key: "files", icon: "📁", label: "本地文件" },
  { key: "docs", icon: "📚", label: "文档库" },
  { key: "videos", icon: "🎬", label: "视频制作" },
];

const API_BASE = process.env.NEXT_PUBLIC_NANOBOT_API_BASE || "http://127.0.0.1:8000";
const SESSION_STORAGE_KEY = "nanobot.sessions.v1";
const CURRENT_SESSION_KEY = "nanobot.current_session_key.v1";

export default function HomePage() {
  const [nav, setNav] = useState<NavKey>("chat");
  const [sidebarPinned, setSidebarPinned] = useState(false);
  const [sidebarHover, setSidebarHover] = useState(false);
  const [info, setInfo] = useState<{
    workspace: string;
    model: string;
    provider: string;
    education_enabled: boolean;
  } | null>(null);

  // Chat
  const [messages, setMessages] = useState<UIChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sessionKey, setSessionKey] = useState("web:console");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Config
  const [configText, setConfigText] = useState("{}");

  // Skills
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPItem[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillItem | null>(null);
  const [skillContent, setSkillContent] = useState("");
  const [mcpConfigText, setMcpConfigText] = useState("{}");

  // Files
  const [filePath, setFilePath] = useState("notes/lesson.md");
  const [fileContent, setFileContent] = useState("");
  const [files, setFiles] = useState<Array<{ name: string; path: string; is_dir: boolean }>>([]);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  // Docs
  const [docsRaw, setDocsRaw] = useState("{}");
  const [docsQueryMode, setDocsQueryMode] = useState<"vector" | "index">("vector");
  const [docsQuery, setDocsQuery] = useState("");
  const [docsResults, setDocsResults] = useState<Array<Record<string, unknown>>>([]);

  // Lesson Wizard
  const [lessonSubject, setLessonSubject] = useState("数学");
  const [lessonGrade, setLessonGrade] = useState("7年级");
  const [lessonDuration, setLessonDuration] = useState(45);
  const [lessonTopic, setLessonTopic] = useState("");
  const [lessonObjectivesText, setLessonObjectivesText] = useState("学生能够通过实例归纳一次函数特征\n学生能够在新情境中判断函数关系");
  const [lessonPriorText, setLessonPriorText] = useState("已掌握坐标系基础\n理解变量和常量概念");
  const [lessonMisText, setLessonMisText] = useState("容易把线性关系与比例关系混淆");
  const [lessonInterestText, setLessonInterestText] = useState("对生活中的打车计费问题感兴趣");
  const [lessonMode, setLessonMode] = useState("讲授型");
  const [lessonKeyPointsText, setLessonKeyPointsText] = useState("一次函数定义\n图像与解析式对应");
  const [lessonDifficultiesText, setLessonDifficultiesText] = useState("从情境抽象出函数模型");
  const [lessonActivities, setLessonActivities] = useState<string[]>([]);
  const [lessonActivityOptions, setLessonActivityOptions] = useState<Array<{ label: string; value: string }>>([]);
  const [lessonNeedsQuiz, setLessonNeedsQuiz] = useState(true);
  const [lessonNeedsRubric, setLessonNeedsRubric] = useState(true);
  const [lessonNeedsDiff, setLessonNeedsDiff] = useState(true);
  const [lessonGeneratedMarkdown, setLessonGeneratedMarkdown] = useState("");
  const [lessonPrompt, setLessonPrompt] = useState("");
  const [lessonPersonaSummary, setLessonPersonaSummary] = useState("");
  const [lessonValidationJson, setLessonValidationJson] = useState("{}");
  const [lessonTemplatesJson, setLessonTemplatesJson] = useState("[]");

  // Videos
  const [teacherProfileJson, setTeacherProfileJson] = useState("{}");
  const [questionnaireMissing, setQuestionnaireMissing] = useState<string[]>([]);
  const [storyboardId, setStoryboardId] = useState("");
  const [storyboardJson, setStoryboardJson] = useState("{}");
  const [storyboardLesson, setStoryboardLesson] = useState("");
  const [segmentNum, setSegmentNum] = useState(1);
  const [segmentPatchJson, setSegmentPatchJson] = useState("{}");
  const [videoTaskId, setVideoTaskId] = useState("");
  const [videoTaskJson, setVideoTaskJson] = useState("{}");
  const [videoListJson, setVideoListJson] = useState("{}");
  const [localVideoPath, setLocalVideoPath] = useState("videos/sample.mp4");
  const [localVideoName, setLocalVideoName] = useState("本地教学视频");
  const [localVideoDesc, setLocalVideoDesc] = useState("");
  const [recommendQueryText, setRecommendQueryText] = useState("");
  const [recommendJson, setRecommendJson] = useState("{}");
  const [exportLessonContent, setExportLessonContent] = useState("");
  const [exportMappingsJson, setExportMappingsJson] = useState("[]");
  const [exportFormat, setExportFormat] = useState("markdown");
  const [exportResult, setExportResult] = useState("{}");
  const [videoAutoRefreshStoryboardId, setVideoAutoRefreshStoryboardId] = useState("");

  function tryParseJson<T>(text: string, fallback: T): T {
    try {
      return JSON.parse(text) as T;
    } catch {
      return fallback;
    }
  }

  function loadSessionsFromStorage(): { sessions: ChatSession[]; current: string | null } {
    try {
      const raw = localStorage.getItem(SESSION_STORAGE_KEY);
      const parsed = raw ? (JSON.parse(raw) as unknown) : [];
      const items = Array.isArray(parsed) ? parsed : [];
      const normalized: ChatSession[] = items
        .map((x) => {
          const obj = x as Record<string, unknown>;
          return {
            key: String(obj.key || ""),
            title: String(obj.title || ""),
            createdAt: Number(obj.createdAt || 0),
          };
        })
        .filter((x) => Boolean(x.key))
        .map((x) => ({ ...x, title: x.title || x.key, createdAt: x.createdAt || Date.now() }))
        .slice(0, 50);
      const cur = localStorage.getItem(CURRENT_SESSION_KEY);
      return { sessions: normalized, current: cur };
    } catch {
      return { sessions: [], current: null };
    }
  }

  function persistSessions(next: ChatSession[], current?: string) {
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(next));
      if (current) localStorage.setItem(CURRENT_SESSION_KEY, current);
    } catch {
    }
  }

  function ensureSessionInList(key: string) {
    setSessions((prev) => {
      if (prev.some((s) => s.key === key)) return prev;
      const next = [...prev, { key, title: key, createdAt: Date.now() }];
      persistSessions(next, key);
      return next;
    });
  }

  useEffect(() => {
    void (async () => {
      try {
        const stored = loadSessionsFromStorage();
        const initialSessions = stored.sessions.length
          ? stored.sessions
          : [{ key: "web:console", title: "默认会话", createdAt: Date.now() }];
        setSessions(initialSessions);
        const initialKey = stored.current && initialSessions.some((s) => s.key === stored.current)
          ? stored.current
          : initialSessions[0].key;
        setSessionKey(initialKey);
        persistSessions(initialSessions, initialKey);

        const [sys, sk, mcp, cfg, fl, docs, hist] = await Promise.all([
          getSystemInfo(),
          listSkills(),
          listMcpServers(),
          getConfig(),
          listFiles("."),
          listDocuments(),
          getChatHistory(initialKey),
        ]);
        setInfo(sys);
        setSkills(sk.skills || []);
        setMcpServers(mcp.servers || []);
        const mcpCfg = await getMcpConfig();
        setMcpConfigText(JSON.stringify(mcpCfg.servers || {}, null, 2));
        setConfigText(JSON.stringify(cfg, null, 2));
        setFiles(fl.entries || []);
        setDocsRaw(JSON.stringify(docs, null, 2));
        setMessages(hist.messages || []);
      } catch (err) {
        void message.error(String(err));
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        ensureSessionInList(sessionKey);
        try {
          localStorage.setItem(CURRENT_SESSION_KEY, sessionKey);
        } catch {
        }
        const hist = await getChatHistory(sessionKey);
        setMessages(hist.messages || []);
      } catch {
        // keep current UI when history fetch fails
      }
    })();
  }, [sessionKey]);

  useEffect(() => {
    void onLoadActivityPack();
  }, [lessonMode, lessonSubject]);

  useEffect(() => {
    if (!videoAutoRefreshStoryboardId) return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const out = await getStoryboard(videoAutoRefreshStoryboardId);
          const sb = (out.storyboard || {}) as Record<string, unknown>;
          setStoryboardJson(JSON.stringify(sb, null, 2));
          const q = (sb.video_queue || {}) as Record<string, unknown>;
          setVideoTaskJson(JSON.stringify(q, null, 2));
          const status = String(q.status || "");
          if (status && status !== "queued" && status !== "running") {
            setVideoAutoRefreshStoryboardId("");
          }
        } catch {
        }
      })();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [videoAutoRefreshStoryboardId]);

  // Auto-scroll chat to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function onSendChat() {
    const text = chatInput.trim();
    if (!text) return;
    const next: UIChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setChatInput("");
    setBusy(true);
    try {
      const out = await sendChat(text, sessionKey);
      setMessages([
        ...next,
        {
          role: "assistant",
          content: out.response || "",
          traces: out.trace || [],
        },
      ]);
    } catch (err) {
      void message.error(String(err));
      setMessages([...next, { role: "assistant", content: "⚠️ " + String(err) }]);
    } finally {
      setBusy(false);
    }
  }

  async function onClearChat() {
    const ok = window.confirm("确认清空当前会话历史吗？该操作会删除当前 Session 的已保存对话。");
    if (!ok) return;
    setBusy(true);
    try {
      await clearChatHistory(sessionKey);
      setMessages([]);
      void message.success("当前会话已清空");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  function newSessionKey() {
    const rand = Math.random().toString(36).slice(2, 7);
    return `web:${Date.now().toString(36)}-${rand}`;
  }

  function onCreateSession() {
    const key = newSessionKey();
    const title = `新会话 ${sessions.length + 1}`;
    const next = [...sessions, { key, title, createdAt: Date.now() }];
    setSessions(next);
    persistSessions(next, key);
    setSessionKey(key);
    setMessages([]);
  }

  function onRenameSession() {
    const current = sessions.find((s) => s.key === sessionKey);
    const name = window.prompt("请输入会话名称：", current?.title || "");
    if (!name || !name.trim()) return;
    const next = sessions.map((s) => (s.key === sessionKey ? { ...s, title: name.trim() } : s));
    setSessions(next);
    persistSessions(next, sessionKey);
  }

  function onOpenSession() {
    const key = window.prompt("请输入要打开的 Session Key：", "");
    if (!key || !key.trim()) return;
    const cleaned = key.trim();
    ensureSessionInList(cleaned);
    setSessionKey(cleaned);
  }

  async function onDeleteSession() {
    const ok = window.confirm("确认删除当前会话吗？该操作会清空该会话的已保存对话，并从列表移除。");
    if (!ok) return;
    setBusy(true);
    try {
      await clearChatHistory(sessionKey);
      const remaining = sessions.filter((s) => s.key !== sessionKey);
      const next = remaining.length
        ? remaining
        : [{ key: "web:console", title: "默认会话", createdAt: Date.now() }];
      const nextKey = next[0].key;
      setSessions(next);
      persistSessions(next, nextKey);
      setSessionKey(nextKey);
      setMessages([]);
      void message.success("会话已删除");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onCopyAssistant(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      void message.success("已复制");
    } catch (err) {
      void message.error("复制失败：" + String(err));
    }
  }

  function onQuoteAssistant(content: string) {
    const lines = content.split("\n");
    const quoted = lines.map((l) => `> ${l}`).join("\n");
    setChatInput((prev) => {
      const next = (quoted + "\n\n" + (prev || "")).trimStart();
      return next;
    });
    setNav("chat");
  }

  function onChatKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void onSendChat();
    }
  }

  async function onSaveTeacherProfile() {
    setBusy(true);
    try {
      const parsed = JSON.parse(teacherProfileJson || "{}") as Record<string, unknown>;
      const payload: Record<string, unknown> = { session_key: sessionKey, ...parsed };
      const out = await updateTeacherProfile(payload);
      setTeacherProfileJson(JSON.stringify(out.profile || {}, null, 2));
      void message.success("画像已更新");
      await loadTeacherProfile();
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveConfig() {
    setBusy(true);
    try {
      const data = JSON.parse(configText) as Record<string, unknown>;
      await updateConfig(data);
      void message.success("配置已保存并重新加载");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onLoadFile() {
    setBusy(true);
    try {
      const out = await readFile(filePath);
      setFileContent(out.content || "");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveFile() {
    setBusy(true);
    try {
      await writeFile(filePath, fileContent);
      void message.success("文件已保存");
      const fl = await listFiles(".");
      setFiles(fl.entries || []);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function refreshLists() {
    try {
      const [fl, docs] = await Promise.all([listFiles("."), listDocuments()]);
      setFiles(fl.entries || []);
      setDocsRaw(JSON.stringify(docs, null, 2));
    } catch {
      // silently ignore refresh errors
    }
  }

  async function onSelectSkill(item: SkillItem) {
    setBusy(true);
    try {
      const out = await getSkill(item.name);
      setSelectedSkill(item);
      setSkillContent(out.content || "");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveSkill() {
    if (!selectedSkill) return;
    setBusy(true);
    try {
      await updateSkill(selectedSkill.name, skillContent, selectedSkill.source);
      const sk = await listSkills();
      setSkills(sk.skills || []);
      void message.success(`已保存 Skill：${selectedSkill.name}`);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveMcp() {
    setBusy(true);
    try {
      const parsed = JSON.parse(mcpConfigText) as Record<string, unknown>;
      await updateMcpConfig(parsed);
      const mcp = await listMcpServers();
      setMcpServers(mcp.servers || []);
      void message.success("MCP 配置已保存");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onQueryDocuments() {
    setBusy(true);
    try {
      const out = await queryDocuments(docsQuery, docsQueryMode, 6);
      setDocsResults(out.results || []);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  function splitLines(text: string): string[] {
    return text
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean);
  }

  async function onLoadActivityPack() {
    setBusy(true);
    try {
      const out = await listActivityPacks({ teaching_mode: lessonMode, subject: lessonSubject, limit: 30 });
      const rows = out.activities || [];
      const options = rows
        .map((x) => String(x.activity || ""))
        .filter(Boolean)
        .map((x) => ({ label: x, value: x }));
      setLessonActivityOptions(options);
      if (!lessonActivities.length) {
        setLessonActivities(options.slice(0, 3).map((x) => x.value));
      }
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onFindTemplates() {
    setBusy(true);
    try {
      const out = await listLessonTemplates({
        subject: lessonSubject,
        grade: lessonGrade,
        teaching_mode: lessonMode,
        topic: lessonTopic,
        limit: 8,
      });
      setLessonTemplatesJson(JSON.stringify(out.templates || [], null, 2));
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateAdvancedLesson() {
    if (!lessonTopic.trim()) {
      void message.warning("请先填写课题名称");
      return;
    }
    setBusy(true);
    try {
      const out = await generateAdvancedLesson({
        session_key: sessionKey,
        subject: lessonSubject,
        grade: lessonGrade,
        topic: lessonTopic,
        duration_minutes: Number(lessonDuration || 45),
        learning_objectives: splitLines(lessonObjectivesText),
        prior_knowledge: splitLines(lessonPriorText),
        misconceptions: splitLines(lessonMisText),
        interests: splitLines(lessonInterestText),
        key_points: splitLines(lessonKeyPointsText),
        difficulties: splitLines(lessonDifficultiesText),
        teaching_mode: lessonMode,
        selected_activities: lessonActivities,
        needs_quiz: lessonNeedsQuiz,
        needs_rubric: lessonNeedsRubric,
        needs_differentiation: lessonNeedsDiff,
        language: "zh",
      });
      setLessonGeneratedMarkdown(out.lesson_markdown || "");
      setLessonPrompt(out.generation_prompt || "");
      setLessonPersonaSummary(out.teacher_persona_summary || "");
      setLessonValidationJson(JSON.stringify(out.validation_report || {}, null, 2));
      setExportLessonContent(out.lesson_markdown || "");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            `## 教案生成结果\n\n` +
            (out.lesson_markdown || "（未返回教案正文）") +
            `\n\n---\n**校验结果**：${out.validation_passed ? "通过" : "存在待优化项"}` +
            (out.teacher_persona_summary ? `\n\n**教师画像摘要**：${out.teacher_persona_summary}` : ""),
          timestamp: new Date().toISOString(),
        },
      ]);
      void message.success(out.validation_passed ? "教案生成完成（已通过校验）" : "教案生成完成（存在待优化项）");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  const uploadProps: UploadProps = {
    fileList,
    multiple: true,
    beforeUpload: () => false,
    onChange: ({ fileList: fl }) => setFileList(fl),
    onRemove: (f) => setFileList((prev) => prev.filter((x) => x.uid !== f.uid)),
  };

  async function onUploadFiles() {
    if (!fileList.length) return;
    setBusy(true);
    try {
      const uploads = await Promise.all(
        fileList.map((f) => {
          if (!f.originFileObj) return Promise.resolve();
          return uploadFile(f.originFileObj as File);
        })
      );

      const uploadedPaths = uploads
        .filter((x): x is { status: string; path: string; size: number } => Boolean(x && x.path))
        .map((x) => x.path);

      const indexed = await Promise.all(
        uploadedPaths.map(async (path) => {
          try {
            await importDocument(path);
            return { path, ok: true as const };
          } catch (err) {
            return { path, ok: false as const, err: String(err) };
          }
        })
      );

      const successCount = indexed.filter((x) => x.ok).length;
      const failCount = indexed.length - successCount;

      if (failCount === 0) {
        void message.success(`${uploadedPaths.length} 个文件已上传并建立索引`);
      } else {
        void message.warning(`上传完成；索引成功 ${successCount} 个，失败 ${failCount} 个`);
      }

      setFileList([]);
      await refreshLists();
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadTeacherProfile() {
    setBusy(true);
    try {
      const [profile, questionnaire] = await Promise.all([
        getTeacherProfile(sessionKey),
        getTeacherQuestionnaire(sessionKey),
      ]);
      setTeacherProfileJson(JSON.stringify(profile.profile || {}, null, 2));
      setQuestionnaireMissing(questionnaire.missing_fields || []);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onCreateStoryboard() {
    if (!storyboardLesson.trim()) {
      void message.warning("请先粘贴教案内容");
      return;
    }
    setBusy(true);
    try {
      const out = await createStoryboard({ lesson_plan: storyboardLesson });
      const sb = out.storyboard || {};
      setStoryboardId(String(sb.id || ""));
      setStoryboardJson(JSON.stringify(sb, null, 2));
      void message.success("已生成分镜草案");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onQuickLessonToVideo() {
    if (!storyboardLesson.trim()) {
      void message.warning("请先粘贴教案内容");
      return;
    }
    setBusy(true);
    try {
      let sbId = storyboardId.trim();
      let sb: Record<string, unknown> = {};
      if (!sbId) {
        const created = await createStoryboard({ lesson_plan: storyboardLesson });
        sb = (created.storyboard || {}) as Record<string, unknown>;
        sbId = String(sb.id || "");
        setStoryboardId(sbId);
        setStoryboardJson(JSON.stringify(sb, null, 2));
      } else {
        const loaded = await getStoryboard(sbId);
        sb = (loaded.storyboard || {}) as Record<string, unknown>;
        setStoryboardJson(JSON.stringify(sb, null, 2));
      }

      if (!sbId) {
        void message.error("分镜创建失败：未获得 storyboard_id");
        return;
      }

      try {
        await confirmStoryboard(sbId);
      } catch {
      }

      const out = await generateVideoFromStoryboard(sbId, { only_selected: true });
      const queue = (out as unknown as { video_queue?: Record<string, unknown> }).video_queue || {};
      setVideoTaskJson(JSON.stringify(queue, null, 2));
      setVideoTaskId("");
      setVideoAutoRefreshStoryboardId(sbId);
      void message.success("已开始生成视频：系统会自动逐段复用/生成并更新进度");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onReloadStoryboard() {
    if (!storyboardId.trim()) return;
    setBusy(true);
    try {
      const out = await getStoryboard(storyboardId);
      setStoryboardJson(JSON.stringify(out.storyboard || {}, null, 2));
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onPatchSegment() {
    if (!storyboardId.trim()) {
      void message.warning("请先填写 storyboard ID");
      return;
    }
    setBusy(true);
    try {
      const patch = JSON.parse(segmentPatchJson || "{}") as Record<string, unknown>;
      const out = await editStoryboardSegment(storyboardId, segmentNum, patch);
      setStoryboardJson(JSON.stringify(out.storyboard || {}, null, 2));
      void message.success("分镜已更新");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmStoryboard() {
    if (!storyboardId.trim()) return;
    setBusy(true);
    try {
      const out = await confirmStoryboard(storyboardId);
      setStoryboardJson(JSON.stringify(out.storyboard || {}, null, 2));
      void message.success("分镜已确认");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateVideoFromStoryboard() {
    if (!storyboardId.trim()) return;
    setBusy(true);
    try {
      const out = await generateVideoFromStoryboard(storyboardId, { only_selected: true });
      const queue = (out as unknown as { video_queue?: Record<string, unknown> }).video_queue || {};
      setVideoTaskJson(JSON.stringify(queue, null, 2));
      setVideoTaskId("");
      void message.success("已启动分镜队列生成");
      try {
        const refreshed = await getStoryboard(storyboardId);
        setStoryboardJson(JSON.stringify(refreshed.storyboard || {}, null, 2));
      } catch {
      }
      setVideoAutoRefreshStoryboardId(storyboardId);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onQueryTask() {
    if (!videoTaskId.trim()) return;
    setBusy(true);
    try {
      const out = await queryArkMediaTask(videoTaskId);
      setVideoTaskJson(JSON.stringify(out, null, 2));
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onImportLocalVideo() {
    setBusy(true);
    try {
      await importLocalVideo({
        path: localVideoPath,
        name: localVideoName,
        description: localVideoDesc,
      });
      void message.success("本地视频已导入");
      await onListVideos();
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onListVideos() {
    setBusy(true);
    try {
      const out = await listVideos();
      setVideoListJson(JSON.stringify(out.videos || [], null, 2));
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRecommendVideos() {
    if (!recommendQueryText.trim()) return;
    setBusy(true);
    try {
      const out = await recommendVideos(recommendQueryText);
      setRecommendJson(JSON.stringify(out.results || [], null, 2));
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onExportLessonVideo() {
    setBusy(true);
    try {
      const mappings = JSON.parse(exportMappingsJson || "[]") as Array<Record<string, string>>;
      const out = await exportLessonVideo({
        lesson_content: exportLessonContent,
        mappings,
        format: exportFormat,
      });
      setExportResult(JSON.stringify(out, null, 2));
      if (out.download_url) {
        window.open(`${API_BASE}${out.download_url}`, "_blank", "noopener,noreferrer");
      }
      void message.success(out.status === "degraded" ? "已降级为 Markdown 导出" : "导出完成");
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onQuickDownloadLesson(format: "markdown" | "docx" | "pdf") {
    if (!lessonGeneratedMarkdown.trim()) {
      void message.warning("请先生成教案后再下载");
      return;
    }
    setBusy(true);
    try {
      const out = await exportLessonVideo({
        lesson_content: lessonGeneratedMarkdown,
        mappings: [],
        format,
      });
      setExportResult(JSON.stringify(out, null, 2));
      if (out.download_url) {
        window.open(`${API_BASE}${out.download_url}`, "_blank", "noopener,noreferrer");
      }
      void message.success(out.status === "degraded" ? "当前环境缺少 pandoc，已下载 Markdown" : `${String(out.format || format).toUpperCase()} 下载已开始`);
    } catch (err) {
      void message.error(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      {/* Window bar */}
      <div className="window-bar">
        <span className="traffic traffic-close" />
        <span className="traffic traffic-min" />
        <span className="traffic traffic-max" />
        <span className="window-title">Nanobot Edu Console</span>
        {info && (
          <span className="window-tags">
            <Tag color="geekblue" style={{ margin: 0 }}>
              {info.model}
            </Tag>
            <Tag color="green" style={{ margin: 0 }}>
              {info.provider}
            </Tag>
          </span>
        )}
      </div>

      <Layout style={{ flex: 1, overflow: "hidden" }} className="app-layout">
        <div
          className="sidebar-hover-zone"
          onMouseEnter={() => setSidebarHover(true)}
          onMouseLeave={() => setSidebarHover(false)}
        />
        {/* Sidebar */}
        <Sider
          width={200}
          className={`app-sider ${sidebarPinned || sidebarHover ? "open" : "closed"}`}
          theme="light"
          onMouseEnter={() => setSidebarHover(true)}
          onMouseLeave={() => setSidebarHover(false)}
        >
          <nav className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <Tooltip key={item.key} title="" placement="right">
                <button
                  className={`nav-item${nav === item.key ? " active" : ""}`}
                  onClick={() => setNav(item.key)}
                >
                  <span className="nav-icon">{item.icon}</span>
                  <span className="nav-label">{item.label}</span>
                </button>
              </Tooltip>
            ))}
          </nav>
          {info && (
            <div className="sidebar-footer">
              <Text type="secondary" style={{ fontSize: 11 }}>
                {info.workspace.split(/[\\/]/).pop()}
              </Text>
              <Button
                size="small"
                style={{ marginTop: 8 }}
                onClick={() => setSidebarPinned((x) => !x)}
              >
                {sidebarPinned ? "取消固定" : "固定面板"}
              </Button>
            </div>
          )}
        </Sider>

        {/* Main content */}
        <Content className="main-content">
          {nav === "chat" && (
            <div className="chat-shell">
              <div className="chat-header">
                <Space wrap>
                  <Select
                    size="small"
                    value={sessionKey}
                    style={{ width: 240 }}
                    options={sessions.map((s) => ({ label: s.title, value: s.key }))}
                    onChange={(v) => setSessionKey(v)}
                  />
                  <Tooltip title={sessionKey}>
                    <Tag color="blue">Session</Tag>
                  </Tooltip>
                  <Button size="small" onClick={() => onCreateSession()}>
                    新建
                  </Button>
                  <Button size="small" onClick={() => onOpenSession()}>
                    打开
                  </Button>
                  <Button size="small" onClick={() => onRenameSession()}>
                    重命名
                  </Button>
                  <Button size="small" danger onClick={() => void onDeleteSession()} loading={busy}>
                    删除
                  </Button>
                </Space>
                <Button
                  size="small"
                  onClick={() => void onClearChat()}
                  style={{ marginLeft: 8 }}
                >
                  清空
                </Button>
              </div>
              <div className="chat-messages">
                {messages.length === 0 && (
                  <div className="chat-empty">
                    <Text type="secondary">输入教学需求，例如：生成七年级一次函数教案</Text>
                  </div>
                )}
                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`bubble-row ${msg.role === "user" ? "bubble-row-user" : "bubble-row-assistant"}`}
                  >
                    <div className={`bubble ${msg.role === "user" ? "bubble-user" : "bubble-assistant"}`}>
                      {msg.role === "assistant" ? (
                        <>
                          {!!msg.content && (
                            <div className="bubble-actions">
                              <Tooltip title="复制这条回复">
                                <Button size="small" type="text" onClick={() => void onCopyAssistant(msg.content)}>
                                  复制
                                </Button>
                              </Tooltip>
                              <Tooltip title="引用到输入框">
                                <Button size="small" type="text" onClick={() => onQuoteAssistant(msg.content)}>
                                  引用
                                </Button>
                              </Tooltip>
                            </div>
                          )}
                          {!!msg.content && (
                            <div className="markdown-body">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                            </div>
                          )}
                          {!!msg.traces?.length && (
                            <div className="trace-panel">
                              {msg.traces.map((tr, tIdx) => (
                                <details key={`${idx}-trace-${tIdx}`} className="trace-details">
                                  <summary>{tr.emoji} {tr.title}</summary>
                                  <pre>{tr.content}</pre>
                                </details>
                              ))}
                            </div>
                          )}
                        </>
                      ) : (
                        <span style={{ whiteSpace: "pre-wrap" }}>{msg.content}</span>
                      )}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="bubble-row bubble-row-assistant">
                    <div className="bubble bubble-assistant bubble-typing">
                      <span className="dot" /><span className="dot" /><span className="dot" />
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
              <div className="chat-input-area">
                <Input.TextArea
                  rows={3}
                  value={chatInput}
                  onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setChatInput(e.target.value)}
                  onKeyDown={onChatKeyDown}
                  placeholder="输入消息… Enter 发送，Shift+Enter 换行"
                  disabled={busy}
                />
                <Button
                  type="primary"
                  loading={busy}
                  onClick={() => void onSendChat()}
                  style={{ marginTop: 8, width: "100%" }}
                >
                  发送
                </Button>
              </div>
            </div>
          )}

          {nav === "lesson" && (
            <div className="page-section">
              <Title level={4}>高级教案生成向导</Title>
              <Paragraph type="secondary">
                通过结构化表单一次性补齐教学关键信息，系统将自动合成专业提示词、生成详细教案并执行教学逻辑校验。
              </Paragraph>

              <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                  <Card title="1) 基础信息" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Select
                        value={lessonSubject}
                        onChange={setLessonSubject}
                        options={[
                          { label: "语文", value: "语文" },
                          { label: "数学", value: "数学" },
                          { label: "英语", value: "英语" },
                          { label: "物理", value: "物理" },
                          { label: "化学", value: "化学" },
                          { label: "生物", value: "生物" },
                        ]}
                      />
                      <Input value={lessonGrade} onChange={(e: ChangeEvent<HTMLInputElement>) => setLessonGrade(e.target.value)} placeholder="年级/学段，如 7年级" />
                      <Input type="number" value={String(lessonDuration)} onChange={(e: ChangeEvent<HTMLInputElement>) => setLessonDuration(Number(e.target.value || "45"))} addonAfter="分钟" />
                      <Input value={lessonTopic} onChange={(e: ChangeEvent<HTMLInputElement>) => setLessonTopic(e.target.value)} placeholder="课题名称（必填）" />
                    </Space>
                  </Card>
                </Col>

                <Col xs={24} lg={12}>
                  <Card title="2) 核心目标（学生能够…）" size="small">
                    <Input.TextArea
                      rows={8}
                      value={lessonObjectivesText}
                      onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonObjectivesText(e.target.value)}
                      placeholder={"每行一个目标，例如：\n学生能够通过实验数据归纳出浮力定律"}
                    />
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                <Col xs={24} lg={8}>
                  <Card title="3) 学情分析：已有基础" size="small">
                    <Input.TextArea rows={7} value={lessonPriorText} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonPriorText(e.target.value)} placeholder="每行一个描述" />
                  </Card>
                </Col>
                <Col xs={24} lg={8}>
                  <Card title="4) 学情分析：常见误区" size="small">
                    <Input.TextArea rows={7} value={lessonMisText} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonMisText(e.target.value)} placeholder="每行一个误区" />
                  </Card>
                </Col>
                <Col xs={24} lg={8}>
                  <Card title="5) 学情分析：兴趣点" size="small">
                    <Input.TextArea rows={7} value={lessonInterestText} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonInterestText(e.target.value)} placeholder="每行一个兴趣点" />
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                <Col xs={24} lg={12}>
                  <Card title="6) 教学重难点" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Input.TextArea rows={4} value={lessonKeyPointsText} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonKeyPointsText(e.target.value)} placeholder="重点（每行一条）" />
                      <Input.TextArea rows={4} value={lessonDifficultiesText} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLessonDifficultiesText(e.target.value)} placeholder="难点（每行一条）" />
                    </Space>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card title="7) 教学模式与关键活动" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Select
                        value={lessonMode}
                        onChange={setLessonMode}
                        options={[
                          { label: "讲授型", value: "讲授型" },
                          { label: "探究发现式", value: "探究发现式" },
                          { label: "小组合作式", value: "小组合作式" },
                          { label: "项目式", value: "项目式" },
                          { label: "翻转课堂", value: "翻转课堂" },
                        ]}
                      />
                      <Select
                        mode="multiple"
                        allowClear
                        placeholder="勾选关键活动"
                        value={lessonActivities}
                        onChange={(vals) => setLessonActivities(vals)}
                        options={lessonActivityOptions}
                      />
                      <Button onClick={() => void onLoadActivityPack()} loading={busy}>刷新活动包建议</Button>
                    </Space>
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                <Col xs={24} lg={12}>
                  <Card title="8) 评估要求" size="small">
                    <Space direction="vertical">
                      <Checkbox checked={lessonNeedsQuiz} onChange={(e) => setLessonNeedsQuiz(e.target.checked)}>我需要设计随堂测验题</Checkbox>
                      <Checkbox checked={lessonNeedsRubric} onChange={(e) => setLessonNeedsRubric(e.target.checked)}>我需要小组合作评价量表</Checkbox>
                      <Checkbox checked={lessonNeedsDiff} onChange={(e) => setLessonNeedsDiff(e.target.checked)}>我需要差异化作业（必做+选做）</Checkbox>
                    </Space>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card title="模板库与案例库" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Button onClick={() => void onFindTemplates()} loading={busy}>查询相近模板</Button>
                      <Input.TextArea rows={8} value={lessonTemplatesJson} readOnly />
                    </Space>
                  </Card>
                </Col>
              </Row>

              <Card title="9) 生成与校验" size="small" style={{ marginTop: 8 }}>
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Space wrap>
                    <Button type="primary" loading={busy} onClick={() => void onGenerateAdvancedLesson()}>生成详细教案</Button>
                    <Text type="secondary">将自动执行：提示词合成 → 教案生成 → 规则校验</Text>
                  </Space>
                  <Space wrap>
                    <Button onClick={() => void onQuickDownloadLesson("docx")} loading={busy}>下载 Word (docx)</Button>
                    <Button onClick={() => void onQuickDownloadLesson("pdf")} loading={busy}>下载 PDF</Button>
                    <Button onClick={() => void onQuickDownloadLesson("markdown")} loading={busy}>下载 Markdown</Button>
                  </Space>
                  <Input.TextArea rows={12} value={lessonGeneratedMarkdown} readOnly placeholder="生成后的详细教案" />
                  <Input.TextArea rows={3} value={lessonPersonaSummary} readOnly placeholder="教师画像摘要（由对话自动提取）" />
                  <Input.TextArea rows={8} value={lessonValidationJson} readOnly placeholder="教学逻辑校验报告" />
                  <Input.TextArea rows={8} value={lessonPrompt} readOnly placeholder="后端合成的专业提示词" />
                </Space>
              </Card>
            </div>
          )}

          {nav === "config" && (
            <div className="page-section">
              <Title level={4}>API 配置</Title>
              <Paragraph type="secondary">
                编辑并保存完整配置（含 API、Skills、MCP、Education）。
              </Paragraph>
              <Input.TextArea
                rows={20}
                value={configText}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setConfigText(e.target.value)}
              />
              <Button
                type="primary"
                loading={busy}
                onClick={() => void onSaveConfig()}
                style={{ marginTop: 8 }}
              >
                保存配置
              </Button>
            </div>
          )}

          {nav === "skills" && (
            <div className="page-section">
              <Title level={4}>Skills / MCP</Title>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <Card title="Skills" size="small">
                    <List
                      size="small"
                      dataSource={skills}
                      renderItem={(item: SkillItem) => (
                        <List.Item
                          onClick={() => void onSelectSkill(item)}
                          style={{ cursor: "pointer" }}
                        >
                          <Space direction="vertical" size={0}>
                            <Text strong>{item.name}</Text>
                            <Text type="secondary">{item.source}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Card>
                </Col>
                <Col xs={24} md={16}>
                  <Card title="Skill 编辑器" size="small">
                    {!selectedSkill ? (
                      <Paragraph type="secondary">从左侧选择一个 Skill 后可查看与修改。</Paragraph>
                    ) : (
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Text>
                          当前: <Text code>{selectedSkill.name}</Text> ({selectedSkill.source})
                        </Text>
                        {selectedSkill.source === "builtin" && (
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            内置 Skill 修改后会自动写入 workspace 覆盖目录：<code>skills/{selectedSkill.name}/SKILL.md</code>
                          </Paragraph>
                        )}
                        <Input.TextArea
                          rows={14}
                          value={skillContent}
                          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setSkillContent(e.target.value)}
                        />
                        <Button type="primary" loading={busy} onClick={() => void onSaveSkill()}>
                          保存 Skill
                        </Button>
                      </Space>
                    )}
                  </Card>
                </Col>
              </Row>

              <Divider />

              <Row gutter={[16, 16]}>
                <Col xs={24}>
                  <Card title="MCP Servers" size="small">
                    {mcpServers.length === 0 ? (
                      <Paragraph type="secondary">
                        当前没有 MCP 服务器。可在下方 JSON 中添加并保存。
                      </Paragraph>
                    ) : (
                      <List
                        size="small"
                        dataSource={mcpServers}
                        renderItem={(item: MCPItem) => (
                          <List.Item>
                            <Space direction="vertical" size={0}>
                              <Text strong>{item.name}</Text>
                              <Text type="secondary">{item.type}</Text>
                              {!!item.url && <Text code>{item.url}</Text>}
                              {!!item.command && <Text code>{item.command}</Text>}
                            </Space>
                          </List.Item>
                        )}
                      />
                    )}

                    <Divider style={{ margin: "12px 0" }} />
                    <Paragraph type="secondary">MCP JSON 配置（保存后会重载 API 配置）。</Paragraph>
                    <Input.TextArea
                      rows={10}
                      value={mcpConfigText}
                      onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setMcpConfigText(e.target.value)}
                    />
                    <Button type="primary" style={{ marginTop: 8 }} onClick={() => void onSaveMcp()}>
                      保存 MCP 配置
                    </Button>
                  </Card>
                </Col>
              </Row>
            </div>
          )}

          {nav === "files" && (
            <div className="page-section">
              <Title level={4}>本地文件</Title>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <Card
                    title="Workspace"
                    size="small"
                    extra={
                      <Button size="small" onClick={() => void refreshLists()}>
                        刷新
                      </Button>
                    }
                  >
                    <List
                      size="small"
                      dataSource={files}
                      renderItem={(item: { name: string; path: string; is_dir: boolean }) => (
                        <List.Item
                          onClick={() => setFilePath(item.path)}
                          style={{ cursor: "pointer" }}
                        >
                          <Text>{item.is_dir ? `📁 ${item.name}` : `📄 ${item.name}`}</Text>
                        </List.Item>
                      )}
                    />
                  </Card>
                  <Card title="上传文件" size="small" style={{ marginTop: 12 }}>
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Upload {...uploadProps}>
                        <Button>选择文件</Button>
                      </Upload>
                      <Button
                        type="primary"
                        loading={busy}
                        disabled={!fileList.length}
                        onClick={() => void onUploadFiles()}
                        block
                      >
                        上传到 documents/uploads
                      </Button>
                    </Space>
                  </Card>
                </Col>
                <Col xs={24} md={16}>
                  <Card title="文件编辑" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Input
                        value={filePath}
                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                          setFilePath(e.target.value)
                        }
                      />
                      <Space>
                        <Button onClick={() => void onLoadFile()} loading={busy}>
                          读取
                        </Button>
                        <Button
                          type="primary"
                          onClick={() => void onSaveFile()}
                          loading={busy}
                        >
                          保存
                        </Button>
                      </Space>
                      <Input.TextArea
                        rows={16}
                        value={fileContent}
                        onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                          setFileContent(e.target.value)
                        }
                      />
                    </Space>
                  </Card>
                </Col>
              </Row>
            </div>
          )}

          {nav === "docs" && (
            <div className="page-section">
              <Title level={4}>文档库</Title>
              <Paragraph type="secondary">
                支持向量检索与索引检索；可直接查看命中的文档内容。
              </Paragraph>

              <Space wrap style={{ marginBottom: 12 }}>
                <Segmented
                  options={[
                    { label: "向量检索", value: "vector" },
                    { label: "索引检索", value: "index" },
                  ]}
                  value={docsQueryMode}
                  onChange={(val) => setDocsQueryMode(val as "vector" | "index")}
                />
                <Input
                  value={docsQuery}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setDocsQuery(e.target.value)}
                  placeholder="输入关键词或问题"
                  style={{ width: 320 }}
                />
                <Button type="primary" loading={busy} onClick={() => void onQueryDocuments()}>
                  查询
                </Button>
              </Space>

              <Row gutter={[16, 16]}>
                <Col xs={24} lg={10}>
                  <Card title="已导入文档索引" size="small">
                    <Input.TextArea rows={20} value={docsRaw} readOnly />
                  </Card>
                </Col>
                <Col xs={24} lg={14}>
                  <Card title="检索结果" size="small">
                    {docsResults.length === 0 ? (
                      <Paragraph type="secondary">暂无结果，先输入查询条件后点击“查询”。</Paragraph>
                    ) : (
                      <List
                        dataSource={docsResults}
                        renderItem={(item) => (
                          <List.Item>
                            <Space direction="vertical" style={{ width: "100%" }}>
                              <Text strong>{String(item.source_path || item.doc_id || "unknown")}</Text>
                              {item.score !== undefined && <Text type="secondary">score: {String(item.score)}</Text>}
                              <Input.TextArea
                                rows={6}
                                readOnly
                                value={String(item.text || item.content || item.full_content || "")}
                              />
                            </Space>
                          </List.Item>
                        )}
                      />
                    )}
                  </Card>
                </Col>
              </Row>
            </div>
          )}

          {nav === "videos" && (
            <div className="page-section">
              <Title level={4}>视频制作与教案映射</Title>
              <Paragraph type="secondary">
                该页面支持教师画像读取、分镜草案编辑确认、任务预览、本地视频复用推荐，以及教案映射导出。
              </Paragraph>

              <Row gutter={[16, 16]}>
                <Col xs={24}>
                  <Card title="快速生成（推荐）" size="small">
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Text type="secondary">1) 粘贴教案  2) 点击“一键生成视频”  3) 等待进度自动刷新  4) 完成后可导出</Text>
                      <Input.TextArea
                        rows={6}
                        value={storyboardLesson}
                        onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setStoryboardLesson(e.target.value)}
                        placeholder="把已有教案草案粘贴到这里"
                      />
                      <Space wrap>
                        <Button type="primary" loading={busy} onClick={() => void onQuickLessonToVideo()}>一键生成视频</Button>
                        <Input
                          value={storyboardId}
                          onChange={(e: ChangeEvent<HTMLInputElement>) => setStoryboardId(e.target.value)}
                          placeholder="已有 storyboard_id 可粘贴（可选）"
                          style={{ width: 260 }}
                        />
                        <Button onClick={() => void onReloadStoryboard()} loading={busy}>刷新进度</Button>
                        <Button onClick={() => setNav("config")} loading={busy}>去配置 API</Button>
                      </Space>
                      <Space wrap>
                        {(() => {
                          const q = tryParseJson<Record<string, unknown>>(videoTaskJson, {});
                          const segments = Array.isArray(q.segments) ? (q.segments as Array<Record<string, unknown>>) : [];
                          const status = String(q.status || "未开始");
                          const doneCount = segments.filter((s) => ["done", "reused"].includes(String(s.status || ""))).length;
                          const failCount = segments.filter((s) => ["failed", "needs_media_config"].includes(String(s.status || ""))).length;
                          const total = segments.length || (q.total_segments ? Number(q.total_segments) : 0);
                          const combined = String(q.combined_local_path || "");
                          return (
                            <>
                              <Text>队列状态：{status}</Text>
                              <Text>进度：{doneCount}/{total || "?"}</Text>
                              {failCount > 0 && <Text type="danger">异常：{failCount}</Text>}
                              {!!combined && <Text>合成视频：{combined}</Text>}
                            </>
                          );
                        })()}
                      </Space>
                      <details>
                        <summary>查看详细信息（可选）</summary>
                        <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
                          <Input.TextArea rows={10} value={videoTaskJson} readOnly placeholder="video_queue JSON" />
                          <Input.TextArea rows={10} value={storyboardJson} readOnly placeholder="storyboard JSON" />
                        </Space>
                      </details>
                    </Space>
                  </Card>
                </Col>
              </Row>

              <details style={{ marginTop: 12 }}>
                <summary>高级功能（可选）</summary>
                <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                  <Col xs={24} lg={12}>
                    <Card title="教师画像" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Space wrap>
                          <Button onClick={() => void loadTeacherProfile()} loading={busy}>读取画像问卷状态</Button>
                          <Button type="primary" onClick={() => void onSaveTeacherProfile()} loading={busy}>保存画像</Button>
                        </Space>
                        <Text type="secondary">待补充字段：{questionnaireMissing.join("、") || "无"}</Text>
                        <Input.TextArea rows={8} value={teacherProfileJson} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setTeacherProfileJson(e.target.value)} />
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} lg={12}>
                    <Card title="分镜草案（高级）" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Space wrap>
                          <Button loading={busy} onClick={() => void onCreateStoryboard()}>只生成分镜</Button>
                          <Button type="primary" onClick={() => void onGenerateVideoFromStoryboard()} loading={busy}>按选中分镜生成视频</Button>
                        </Space>
                        <Input.TextArea rows={10} value={storyboardJson} readOnly />
                      </Space>
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                  <Col xs={24} lg={12}>
                    <Card title="分镜片段编辑与确认" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Input
                          type="number"
                          value={String(segmentNum)}
                          onChange={(e: ChangeEvent<HTMLInputElement>) => setSegmentNum(Number(e.target.value || "1"))}
                          addonBefore="segment"
                          style={{ width: 180 }}
                        />
                        <Input.TextArea
                          rows={6}
                          value={segmentPatchJson}
                          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setSegmentPatchJson(e.target.value)}
                          placeholder='例如 {"scene_text":"...","selected":true}'
                        />
                        <Space wrap>
                          <Button onClick={() => void onPatchSegment()} loading={busy}>更新片段</Button>
                          <Button onClick={() => void onConfirmStoryboard()} loading={busy}>确认分镜</Button>
                        </Space>
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} lg={12}>
                    <Card title="视频任务预览（ARK）" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Input
                          value={videoTaskId}
                          onChange={(e: ChangeEvent<HTMLInputElement>) => setVideoTaskId(e.target.value)}
                          placeholder="任务ID，如 cgt-2025..."
                        />
                        <Button onClick={() => void onQueryTask()} loading={busy}>查询任务状态</Button>
                        <Input.TextArea rows={10} value={videoTaskJson} readOnly />
                      </Space>
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
                  <Col xs={24} lg={12}>
                    <Card title="本地视频导入与复用推荐" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Input value={localVideoPath} onChange={(e: ChangeEvent<HTMLInputElement>) => setLocalVideoPath(e.target.value)} placeholder="工作区内视频路径" />
                        <Input value={localVideoName} onChange={(e: ChangeEvent<HTMLInputElement>) => setLocalVideoName(e.target.value)} placeholder="视频名称" />
                        <Input.TextArea rows={3} value={localVideoDesc} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setLocalVideoDesc(e.target.value)} placeholder="视频说明" />
                        <Space wrap>
                          <Button onClick={() => void onImportLocalVideo()} loading={busy}>导入本地视频</Button>
                          <Button onClick={() => void onListVideos()} loading={busy}>刷新视频库</Button>
                        </Space>
                        <Input
                          value={recommendQueryText}
                          onChange={(e: ChangeEvent<HTMLInputElement>) => setRecommendQueryText(e.target.value)}
                          placeholder="输入分镜文本关键词进行复用推荐"
                        />
                        <Button onClick={() => void onRecommendVideos()} loading={busy}>推荐可复用视频</Button>
                        <Input.TextArea rows={7} value={recommendJson} readOnly />
                        <Input.TextArea rows={6} value={videoListJson} readOnly />
                      </Space>
                    </Card>
                  </Col>
                  <Col xs={24} lg={12}>
                    <Card title="教案阶段与视频映射导出" size="small">
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Input.TextArea
                          rows={6}
                          value={exportLessonContent}
                          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setExportLessonContent(e.target.value)}
                          placeholder="教案正文"
                        />
                        <Input.TextArea
                          rows={5}
                          value={exportMappingsJson}
                          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setExportMappingsJson(e.target.value)}
                          placeholder='映射 JSON，例如 [{"stage":"导入","video_name":"...","video_url":"..."}]'
                        />
                        <Segmented
                          options={[
                            { label: "Markdown", value: "markdown" },
                            { label: "DOCX", value: "docx" },
                            { label: "PDF", value: "pdf" },
                          ]}
                          value={exportFormat}
                          onChange={(val) => setExportFormat(String(val))}
                        />
                        <Button type="primary" onClick={() => void onExportLessonVideo()} loading={busy}>导出文档</Button>
                        <Input.TextArea rows={6} value={exportResult} readOnly />
                      </Space>
                    </Card>
                  </Col>
                </Row>
              </details>
            </div>
          )}
        </Content>
      </Layout>
    </div>
  );
}
