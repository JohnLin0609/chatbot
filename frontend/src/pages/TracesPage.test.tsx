import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../components/NavBar", () => ({ default: () => null }));

vi.mock("../api/client", () => ({
  listTraces: vi.fn(async () => ({
    traces: [
      {
        id: 11,
        created_at: "2026-06-08T10:00:00",
        user_id: "7",
        session_key: "web:7:c1",
        rag_tier: "complex",
        reranked: true,
        query_preview: "how long for a refund?",
        prompt_tokens: 120,
        completion_tokens: 8,
        total_latency_ms: 90,
        model: "gpt-x",
        provider: "openai",
      },
    ],
    total: 1,
    limit: 25,
    offset: 0,
  })),
}));

import TracesPage from "./TracesPage";

it("renders the trace list with a row and filters", async () => {
  render(
    <MemoryRouter>
      <TracesPage />
    </MemoryRouter>,
  );

  await screen.findByText("how long for a refund?");
  expect(screen.getByText("Eval traces")).toBeInTheDocument();
  // a tier filter + the row's tier/tokens
  expect(screen.getByText("Tier")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "complex" })).toBeInTheDocument();
  expect(screen.getByText("120/8")).toBeInTheDocument();
  expect(screen.getByText("1–1 of 1")).toBeInTheDocument();
});
