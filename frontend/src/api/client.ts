import type {
  ChatResponse,
  Chunk,
  DocumentMeta,
  FeedbackSummary,
  IngestResult,
  SystemPrompt,
  TokenResponse,
  User,
} from "./types";

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

export const ingestPptx = (file: File, title: string) => {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
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
