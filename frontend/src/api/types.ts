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
