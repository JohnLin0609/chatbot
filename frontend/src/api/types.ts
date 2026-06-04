export interface User {
  id: number;
  email: string;
  role: "user" | "admin";
  is_active?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
}

export interface DocumentMeta {
  doc_id: string;
  title: string | null;
  doc_type: string;
  enabled: boolean;
  chunk_count: number;
}

export interface Chunk {
  chunk_index: number;
  text: string;
  title: string | null;
  metadata: Record<string, unknown>;
  enabled: boolean;
}

export interface IngestResult {
  doc_id: string;
  chunks_ingested: number;
}
