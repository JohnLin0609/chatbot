import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../components/NavBar", () => ({ default: () => null }));

vi.mock("../api/client", () => ({
  listGolden: vi.fn(async () => [
    {
      id: 1,
      query: "how long for a refund?",
      reference_answer: "14 days",
      notes: null,
      relevant_chunks: [{ doc_id: "d1", chunk_index: 0, relevance: 1 }],
    },
  ]),
  listDocuments: vi.fn(async () => [
    { doc_id: "d1", title: "Refund Policy", doc_type: "prose", enabled: true, chunk_count: 1 },
  ]),
  latestGoldenRun: vi.fn(async () => ({})),
  getChunks: vi.fn(async () => ({ document: {}, chunks: [] })),
  createGolden: vi.fn(),
  updateGolden: vi.fn(),
  deleteGolden: vi.fn(),
  runGoldenEval: vi.fn(async () => ({
    run_id: 1,
    num_queries: 1,
    k_values: [1, 3],
    aggregate: { recall: { "1": 0.5, "3": 1 }, ndcg: { "3": 0.9 }, mrr: 0.8, correctness: 0.7 },
    results: [
      {
        golden_query_id: 1,
        metrics: { recall: { "1": 1, "3": 1 }, ndcg: { "3": 0.95 }, mrr: 1 },
        correctness: 0.7,
        correctness_reasoning: "matches",
        generated_answer: "14 days",
      },
    ],
  })),
}));

import GoldenPage from "./GoldenPage";

it("lists golden queries and shows eval results after running", async () => {
  render(<GoldenPage />);

  // existing golden query renders
  await screen.findByText("how long for a refund?");
  expect(screen.getByText(/1 relevant chunk/)).toBeInTheDocument();

  // run eval -> results table appears with the Recall@k header + correctness mean
  await userEvent.click(screen.getByRole("button", { name: /run eval/i }));
  await screen.findByLabelText("eval results");
  expect(screen.getByText("Recall@1")).toBeInTheDocument();
  // aggregate correctness mean (0.70) is shown
  expect(screen.getAllByText("0.70").length).toBeGreaterThan(0);
});
