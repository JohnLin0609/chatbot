import type {
  ChatResponse,
  Chunk,
  Dashboard,
  DocumentMeta,
  FeedbackSummary,
  GoldenChunk,
  GoldenQuery,
  GoldenRun,
  IngestResult,
  SystemPrompt,
  TokenResponse,
  TraceDetail,
  TraceList,
  User,
} from "./types";

interface GoldenInput {
  query: string;
  reference_answer?: string | null;
  notes?: string | null;
  relevant_chunks: GoldenChunk[];
}

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8753";
const TOKEN_KEY = "cc_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

interface Opts {
  method?: string;
  body?: unknown;
  form?: FormData;
  auth?: boolean; // default true
}

export async function apiFetch<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const init: RequestInit = { method: opts.method ?? "GET", headers };

  if (opts.form) {
    init.body = opts.form; // browser sets multipart boundary
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  if (opts.auth !== false) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }

  const res = await fetch(`${BASE}${path}`, init);

  if (res.status === 401) {
    setToken(null);
    onUnauthorized?.();
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const j = await res.json();
      detail = j?.detail ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- typed helpers -------------------------------------------------------
export const register = (email: string, password: string) =>
  apiFetch<TokenResponse>("/auth/register", {
    method: "POST",
    body: { email, password },
    auth: false,
  });

export const login = (email: string, password: string) =>
  apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
  });

export const me = () => apiFetch<User>("/auth/me");

export const chat = (message: string, conversation_id: string) =>
  apiFetch<ChatResponse>("/chat", {
    method: "POST",
    body: { message, conversation_id },
  });

export const listDocuments = () =>
  apiFetch<{ documents: DocumentMeta[] }>("/documents").then((r) => r.documents);

export const getChunks = (docId: string) =>
  apiFetch<{ document: DocumentMeta; chunks: Chunk[] }>(
    `/documents/${encodeURIComponent(docId)}/chunks`,
  );

export const toggleDocument = (docId: string, enabled: boolean) =>
  apiFetch<{ document: DocumentMeta }>(
    `/documents/${encodeURIComponent(docId)}`,
    { method: "PATCH", body: { enabled } },
  );

export const ingestText = (text: string, title: string, doc_type: string) =>
  apiFetch<IngestResult>("/ingest", {
    method: "POST",
    body: { text, title: title || null, doc_type },
  });

export const ingestPptx = (
  file: File,
  title: string,
  skipLeading = 0,
  skipTrailing = 0,
) => {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  form.append("skip_leading", String(skipLeading));
  form.append("skip_trailing", String(skipTrailing));
  return apiFetch<IngestResult>("/ingest/pptx", { method: "POST", form });
};

export const deleteSession = (conversationId: string) =>
  apiFetch<void>(`/sessions/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
  });

export const sendFeedback = (messageId: number, rating: number) =>
  apiFetch<{ message_id: number; rating: number }>(
    `/messages/${messageId}/feedback`,
    { method: "POST", body: { rating } },
  );

export const getSystemPrompt = () => apiFetch<SystemPrompt>("/admin/system-prompt");

export const setSystemPrompt = (prompt: string) =>
  apiFetch<SystemPrompt>("/admin/system-prompt", {
    method: "PUT",
    body: { prompt },
  });

export const getFeedbackSummary = () =>
  apiFetch<FeedbackSummary>("/admin/feedback/summary");

// ---- golden eval set --------------------------------------------------------
export const listGolden = () =>
  apiFetch<{ queries: GoldenQuery[] }>("/admin/golden").then((r) => r.queries);

export const createGolden = (body: GoldenInput) =>
  apiFetch<GoldenQuery>("/admin/golden", { method: "POST", body });

export const updateGolden = (id: number, body: GoldenInput) =>
  apiFetch<GoldenQuery>(`/admin/golden/${id}`, { method: "PUT", body });

export const deleteGolden = (id: number) =>
  apiFetch<void>(`/admin/golden/${id}`, { method: "DELETE" });

export const runGoldenEval = (k_values?: number[]) =>
  apiFetch<GoldenRun>("/admin/golden/eval", {
    method: "POST",
    body: { k_values: k_values ?? null },
  });

export const latestGoldenRun = () =>
  apiFetch<GoldenRun>("/admin/golden/runs/latest");

export const getDashboard = () => apiFetch<Dashboard>("/admin/dashboard");

// ---- eval trace debug viewer ------------------------------------------------
export interface TraceFilters {
  tier?: string;
  user_id?: string;
  session_key?: string;
  limit?: number;
  offset?: number;
}

export const listTraces = (filters: TraceFilters = {}) => {
  const q = new URLSearchParams();
  if (filters.tier) q.set("tier", filters.tier);
  if (filters.user_id) q.set("user_id", filters.user_id);
  if (filters.session_key) q.set("session_key", filters.session_key);
  q.set("limit", String(filters.limit ?? 50));
  q.set("offset", String(filters.offset ?? 0));
  return apiFetch<TraceList>(`/admin/eval/traces?${q.toString()}`);
};

export const getTrace = (id: number) =>
  apiFetch<TraceDetail>(`/admin/eval/traces/${id}`);
