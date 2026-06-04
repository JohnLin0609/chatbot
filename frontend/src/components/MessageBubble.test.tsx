import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import MessageBubble from "./MessageBubble";

it("renders a user bubble", () => {
  render(<MessageBubble message={{ role: "user", content: "hi" }} />);
  expect(screen.getByText("hi")).toHaveAttribute("data-role", "user");
});

it("renders an assistant bubble", () => {
  render(<MessageBubble message={{ role: "assistant", content: "yo" }} />);
  expect(screen.getByText("yo")).toHaveAttribute("data-role", "assistant");
});

it("shows no feedback controls without a replyId", () => {
  render(<MessageBubble message={{ role: "assistant", content: "yo" }} onFeedback={() => {}} />);
  expect(screen.queryByLabelText("thumbs up")).toBeNull();
});

it("fires onFeedback for an assistant reply with a replyId", async () => {
  const onFeedback = vi.fn();
  render(
    <MessageBubble
      message={{ role: "assistant", content: "yo", replyId: 7 }}
      onFeedback={onFeedback}
    />,
  );
  await userEvent.click(screen.getByLabelText("thumbs up"));
  expect(onFeedback).toHaveBeenCalledWith(7, 1);
  await userEvent.click(screen.getByLabelText("thumbs down"));
  expect(onFeedback).toHaveBeenCalledWith(7, -1);
});

it("reflects the active rating via aria-pressed", () => {
  render(
    <MessageBubble
      message={{ role: "assistant", content: "yo", replyId: 7, rating: 1 }}
      onFeedback={() => {}}
    />,
  );
  expect(screen.getByLabelText("thumbs up")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("thumbs down")).toHaveAttribute("aria-pressed", "false");
});
