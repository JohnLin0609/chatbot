import type { Message } from "../lib/conversations";

export default function MessageBubble({
  message,
  onFeedback,
}: {
  message: Message;
  onFeedback?: (replyId: number, rating: number) => void;
}) {
  const isUser = message.role === "user";
  const canRate = !isUser && typeof message.replyId === "number" && onFeedback;
  const rating = message.rating ?? 0;

  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        data-role={message.role}
        className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
          isUser ? "bg-brand text-white" : "border bg-white text-gray-800"
        }`}
      >
        {message.content}
      </div>
      {canRate && (
        <div className="mt-1 flex gap-1">
          <button
            aria-label="thumbs up"
            aria-pressed={rating === 1}
            onClick={() => onFeedback!(message.replyId!, 1)}
            className={`rounded px-1.5 text-sm ${
              rating === 1 ? "bg-green-100" : "opacity-50 hover:opacity-100"
            }`}
          >
            👍
          </button>
          <button
            aria-label="thumbs down"
            aria-pressed={rating === -1}
            onClick={() => onFeedback!(message.replyId!, -1)}
            className={`rounded px-1.5 text-sm ${
              rating === -1 ? "bg-red-100" : "opacity-50 hover:opacity-100"
            }`}
          >
            👎
          </button>
        </div>
      )}
    </div>
  );
}
