import { render, screen } from "@testing-library/react";

vi.mock("../components/NavBar", () => ({ default: () => null }));

vi.mock("../api/client", () => ({
  getDashboard: vi.fn(async () => ({
    overview: {
      traces: 7,
      judged_traces: 5,
      golden_queries: 2,
      feedback_up: 3,
      feedback_down: 1,
      llm_calls: 20,
    },
    generation: {
      series: [
        { run: "r1", at: "2026-06-06", faithfulness: 0.8, answer_relevance: 0.9, context_utilization: 0.7 },
      ],
      current: { faithfulness: 0.8, answer_relevance: 0.9, context_utilization: 0.7 },
    },
    retrieval: {
      series: [{ run: "r1", at: "2026-06-06", precision: { "1": 1, "3": 0.5 }, ndcg: { "1": 1, "3": 0.9 }, hit_rate: { "1": 1, "3": 1 }, mrr: 1 }],
      current: { precision: { "1": 1, "3": 0.5 }, ndcg: { "1": 1, "3": 0.9 }, hit_rate: { "1": 1, "3": 1 }, mrr: 1 },
    },
    cost: {
      series: [{ day: "2026-06-06", calls: 20, prompt_tokens: 1000, completion_tokens: 300, avg_latency_ms: 150 }],
      by_call_type: [{ call_type: "main_reply", calls: 10, tokens: 800, avg_latency_ms: 120 }],
      totals: { calls: 20, tokens: 1300 },
    },
    golden: {
      series: [{ run_id: 1, at: "2026-06-06", num_queries: 2, aggregate: { recall: { "3": 0.8 }, correctness: 0.75 } }],
      current: null,
    },
    k_values: [1, 3],
  })),
}));

import DashboardPage from "./DashboardPage";

it("renders the four panels with data + charts", async () => {
  render(<DashboardPage />);

  // overview tiles
  await screen.findByText("Generation quality (judge)");
  expect(screen.getByText("Traces")).toBeInTheDocument();

  // panels present
  expect(screen.getByText(/Retrieval quality/)).toBeInTheDocument();
  expect(screen.getByText("Cost & latency (by day)")).toBeInTheDocument();
  expect(screen.getByText("Golden eval history")).toBeInTheDocument();

  // a chart rendered + cost-by-type table value
  expect(screen.getAllByLabelText("sparkline").length).toBeGreaterThan(0);
  expect(screen.getByText("main_reply")).toBeInTheDocument();
});
