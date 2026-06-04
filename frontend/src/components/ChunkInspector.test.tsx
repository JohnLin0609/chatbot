import { render, screen } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getChunks: vi.fn(async () => ({
    document: {},
    chunks: [
      { chunk_index: 0, text: "hello world", title: "Doc", metadata: { slide_number: 1 }, enabled: true },
      { chunk_index: 1, text: "second chunk", title: "Doc", metadata: {}, enabled: false },
    ],
  })),
}));

import ChunkInspector from "./ChunkInspector";

it("renders one card per chunk with metadata + enabled state", async () => {
  render(<ChunkInspector docId="d1" />);
  await screen.findByText("hello world");
  expect(screen.getAllByTestId("chunk-card")).toHaveLength(2);
  expect(screen.getByText("slide 1")).toBeInTheDocument();
  expect(screen.getByText("enabled")).toBeInTheDocument();
  expect(screen.getByText("disabled")).toBeInTheDocument();
});
