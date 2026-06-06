import { render, screen } from "@testing-library/react";

import { Bars, Sparkline, Stat } from "./charts";

it("Stat renders label and value", () => {
  render(<Stat label="Traces" value="5" />);
  expect(screen.getByText("Traces")).toBeInTheDocument();
  expect(screen.getByText("5")).toBeInTheDocument();
});

it("Sparkline draws a polyline for >1 point (nulls skipped)", () => {
  const { container } = render(<Sparkline values={[0.2, null, 0.8, 1]} />);
  const poly = container.querySelector("polyline");
  expect(poly).not.toBeNull();
  // 3 non-null points -> 3 coordinate pairs
  expect(poly!.getAttribute("points")!.trim().split(" ")).toHaveLength(3);
});

it("Sparkline shows 'no data' when all null", () => {
  render(<Sparkline values={[null, undefined]} />);
  expect(screen.getByText("no data")).toBeInTheDocument();
});

it("Bars renders a row per item with formatted value", () => {
  render(<Bars items={[{ label: "P@1", value: 0.5 }, { label: "P@3", value: null }]} />);
  expect(screen.getByText("P@1")).toBeInTheDocument();
  expect(screen.getByText("0.50")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
});
