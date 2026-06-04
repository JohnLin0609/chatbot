import { render, screen } from "@testing-library/react";

import MessageBubble from "./MessageBubble";

it("renders a user bubble", () => {
  render(<MessageBubble message={{ role: "user", content: "hi" }} />);
  expect(screen.getByText("hi")).toHaveAttribute("data-role", "user");
});

it("renders an assistant bubble", () => {
  render(<MessageBubble message={{ role: "assistant", content: "yo" }} />);
  expect(screen.getByText("yo")).toHaveAttribute("data-role", "assistant");
});
