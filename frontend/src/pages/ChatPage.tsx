import { type FormEvent, useEffect, useRef, useState } from "react";

import * as api from "../api/client";
import NavBar from "../components/NavBar";
import MessageBubble from "../components/MessageBubble";
import { Button, errorMessage } from "../components/ui";
import {
  type Conversation,
  appendMessage,
  loadConversations,
  newConversation,
  saveConversations,
} from "../lib/conversations";

export default function ChatPage() {
  const [convos, setConvos] = useState<Conversation[]>(() => {
    const existing = loadConversations();
    return existing.length ? existing : [newConversation()];
  });
  const [activeId, setActiveId] = useState<string>(() => convos[0].id);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const active = convos.find((c) => c.id === activeId) ?? convos[0];

  useEffect(() => saveConversations(convos), [convos]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active.messages.length, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setConvos((cs) => appendMessage(cs, activeId, { role: "user", content: text }));
    setBusy(true);
    try {
      const r = await api.chat(text, activeId);
      setConvos((cs) =>
        appendMessage(cs, activeId, { role: "assistant", content: r.reply }),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function addConversation() {
    const c = newConversation();
    setConvos((cs) => [c, ...cs]);
    setActiveId(c.id);
  }

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex min-h-0 flex-1">
        <aside className="w-60 overflow-y-auto border-r bg-white p-2">
          <Button onClick={addConversation} className="mb-2 w-full">
            New chat
          </Button>
          {convos.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveId(c.id)}
              className={`block w-full truncate rounded px-2 py-1.5 text-left text-sm ${
                c.id === activeId
                  ? "bg-gray-100 font-medium"
                  : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {c.title}
            </button>
          ))}
        </aside>

        <main className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {active.messages.length === 0 && (
              <p className="mt-8 text-center text-sm text-gray-400">
                Ask anything…
              </p>
            )}
            {active.messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
            {busy && (
              <div className="text-sm text-gray-400">Assistant is thinking…</div>
            )}
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div ref={endRef} />
          </div>

          <div className="border-t bg-white p-3">
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                send();
              }}
              className="flex gap-2"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Message…"
                className="flex-1 rounded-md border px-3 py-2 text-sm focus:border-brand focus:outline-none"
              />
              <Button type="submit" disabled={busy || !input.trim()}>
                Send
              </Button>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}
