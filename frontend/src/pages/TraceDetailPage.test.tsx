import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../components/NavBar", () => ({ default: () => null }));

vi.mock("../api/client", () => ({ getTrace: vi.fn() }));

import * as api from "../api/client";
import TraceDetailPage from "./TraceDetailPage";

const mockGet = api.getTrace as unknown as ReturnType<typeof vi.fn>;

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/admin/eval/traces/11"]}>
      <Routes>
        <Route path="/admin/eval/traces/:id" element={<TraceDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const baseTrace = {
  id: 11,
  created_at: "2026-06-08T10:00:00",
  user_id: "7",
  session_key: "web:7:c1",
  conversation_id: "7:c1",
  query: "how long for a refund?",
  rag_tier: "complex",
  reranked: true,
  reply_text: "Within 14 days.",
  reply_message_id: 42,
  system_prompt: "You are helpful.",
  knowledge_text: "[1] refunds within 14 days",
  prompt_tokens: 120,
  completion_tokens: 8,
  model: "gpt-x",
  provider: "openai",
  tool_calls_count: 0,
  retrieval_latency_ms: 12,
  generation_latency_ms: 80,
  total_latency_ms: 92,
};

it("renders the four panels with segments, chunks and judge", async () => {
  mockGet.mockResolvedValue({
    trace: baseTrace,
    segments: [
      { kind: "system_prompt", label: "System prompt", content: "You are helpful.", tokens: 4, pct: 0.2 },
      { kind: "rag_knowledge", label: "RAG knowledge (tier-4)", content: "[1] refunds within 14 days", tokens: 8, pct: 0.4 },
      { kind: "current_query", label: "Current query", content: "how long for a refund?", tokens: 8, pct: 0.4 },
    ],
    messages: [{ role: "system", content: "You are helpful." }],
    bodies_logged: true,
    chunks: [
      { id: 1, doc_id: "d1", chunk_index: 0, title: "Refund Policy", chunk_text: "refunds within 14 days", fused_score: 0.9, fused_rank: 1, rerank_score: 0.95, final_rank: 0, included: true },
    ],
    judge: {
      run_id: "r_new",
      at: "2026-06-08T11:00:00",
      provider: "openai",
      model: "judge-x",
      metrics: [{ metric: "faithfulness", score: 0.9, reasoning: "grounded" }],
      chunk_labels: [{ chunk_ref_id: 1, title: "Refund Policy", relevance: 1, reasoning: "on-topic" }],
    },
  });

  renderAt();

  await screen.findByText("Trace #11");
  // semantic segments
  expect(screen.getByText("System prompt")).toBeInTheDocument();
  expect(screen.getByText("RAG knowledge (tier-4)")).toBeInTheDocument();
  expect(screen.getByText("Current query")).toBeInTheDocument();
  // panels
  expect(screen.getByText("Prompt structure")).toBeInTheDocument();
  expect(screen.getByText("Retrieval candidates")).toBeInTheDocument();
  expect(screen.getByText("LLM-as-judge")).toBeInTheDocument();
  // judge score reasoning + chunk label
  expect(screen.getByText("grounded")).toBeInTheDocument();
  expect(screen.getByText("on-topic")).toBeInTheDocument();
  expect(screen.getByText("Copy raw messages JSON")).toBeInTheDocument();
});

it("shows a notice and disables copy when bodies were not logged", async () => {
  mockGet.mockResolvedValue({
    trace: { ...baseTrace, query: null, reply_text: null },
    segments: [],
    messages: null,
    bodies_logged: false,
    chunks: [],
    judge: null,
  });

  renderAt();

  await screen.findByText("Trace #11");
  expect(screen.getByText(/Message bodies were not logged/)).toBeInTheDocument();
  expect(screen.getByText(/Not judged yet/)).toBeInTheDocument();
  // no copy button in the not-logged branch
  expect(screen.queryByText("Copy raw messages JSON")).not.toBeInTheDocument();
});
