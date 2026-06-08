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
  reply_message_id?: number | null;
}

export interface SystemPrompt {
  prompt: string;
  is_default: boolean;
  default: string;
}

export interface FeedbackSummary {
  up: number;
  down: number;
  recent_negative: {
    message_id: number;
    content: string;
    at: string | null;
  }[];
}

export interface GoldenChunk {
  doc_id: string;
  chunk_index: number;
  relevance: number;
}

export interface GoldenQuery {
  id: number;
  query: string;
  reference_answer: string | null;
  notes: string | null;
  relevant_chunks: GoldenChunk[];
  created_at?: string;
}

export interface MetricBundle {
  recall: Record<string, number | null>;
  precision: Record<string, number | null>;
  ndcg: Record<string, number | null>;
  hit_rate: Record<string, number | null>;
  mrr: number | null;
}

export interface GoldenResult {
  golden_query_id: number;
  metrics: MetricBundle;
  correctness: number | null;
  correctness_reasoning: string | null;
  generated_answer: string | null;
}

export interface GoldenRun {
  run_id: number;
  num_queries: number;
  k_values?: number[];
  aggregate: MetricBundle & { correctness: number | null };
  results?: GoldenResult[];
  created_at?: string;
}

type KMap = Record<string, number | null>;

export interface Dashboard {
  overview: {
    traces: number;
    judged_traces: number;
    golden_queries: number;
    feedback_up: number;
    feedback_down: number;
    llm_calls: number;
  };
  generation: {
    series: {
      run: string;
      at: string | null;
      faithfulness: number | null;
      answer_relevance: number | null;
      context_utilization: number | null;
    }[];
    current: Record<string, number | null>;
  };
  retrieval: {
    series: {
      run: string;
      at: string | null;
      precision: KMap;
      ndcg: KMap;
      hit_rate: KMap;
      mrr: number | null;
    }[];
    current: {
      precision: KMap;
      ndcg: KMap;
      hit_rate: KMap;
      mrr: number | null;
    } | null;
  };
  cost: {
    series: {
      day: string;
      calls: number;
      prompt_tokens: number;
      completion_tokens: number;
      avg_latency_ms: number | null;
    }[];
    by_call_type: {
      call_type: string;
      calls: number;
      tokens: number;
      avg_latency_ms: number | null;
    }[];
    totals: { calls: number; tokens: number };
  };
  golden: {
    series: {
      run_id: number;
      at: string | null;
      num_queries: number;
      aggregate: (MetricBundle & { correctness: number | null }) | null;
    }[];
    current: unknown;
  };
  k_values: number[];
}

// ---- eval trace debug viewer ------------------------------------------------
export interface TraceListRow {
  id: number;
  created_at: string | null;
  user_id: string | null;
  session_key: string | null;
  rag_tier: string | null;
  reranked: boolean;
  query_preview: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_latency_ms: number | null;
  model: string | null;
  provider: string | null;
}

export interface TraceList {
  traces: TraceListRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface PromptSegment {
  kind: string;
  label: string;
  content: string;
  tokens: number;
  pct: number;
  turns?: { role: string; content: string }[];
}

export interface TraceChunk {
  id: number;
  doc_id: string | null;
  chunk_index: number | null;
  title: string | null;
  chunk_text: string | null;
  fused_score: number | null;
  fused_rank: number | null;
  rerank_score: number | null;
  final_rank: number | null;
  included: boolean;
}

export interface TraceJudge {
  run_id: string | null;
  at: string | null;
  provider: string | null;
  model: string | null;
  metrics: { metric: string; score: number | null; reasoning: string | null }[];
  chunk_labels: {
    chunk_ref_id: number | null;
    title: string | null;
    relevance: number | null;
    reasoning: string | null;
  }[];
}

export interface TraceDetail {
  trace: {
    id: number;
    created_at: string | null;
    user_id: string | null;
    session_key: string | null;
    conversation_id: string | null;
    query: string | null;
    rag_tier: string | null;
    reranked: boolean;
    reply_text: string | null;
    reply_message_id: number | null;
    system_prompt: string | null;
    knowledge_text: string | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    model: string | null;
    provider: string | null;
    tool_calls_count: number;
    retrieval_latency_ms: number | null;
    generation_latency_ms: number | null;
    total_latency_ms: number | null;
  };
  segments: PromptSegment[];
  messages: { role: string; content: string }[] | null;
  bodies_logged: boolean;
  chunks: TraceChunk[];
  judge: TraceJudge | null;
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
