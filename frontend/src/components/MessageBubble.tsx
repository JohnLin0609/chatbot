import type { Message } from "../lib/conversations";

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        data-role={message.role}
        className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
          isUser
            ? "bg-brand text-white"
            : "border bg-white text-gray-800"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
