import { type FormEvent, useEffect, useRef, useState } from "react";

import * as api from "../api/client";
import { useAuth } from "../auth/AuthContext";
import NavBar from "../components/NavBar";
import MessageBubble from "../components/MessageBubble";
import { Button, errorMessage } from "../components/ui";
import {
  type Conversation,
  MAX_CONVERSATIONS,
  appendMessage,
  capConversations,
  loadConversations,
  newConversation,
  saveConversations,
  setRating,
} from "../lib/conversations";

export default function ChatPage() {
  const { user } = useAuth();
  const uid = user!.id;

  const [convos, setConvos] = useState<Conversation[]>(() => {
    const existing = loadConversations(uid);
    return existing.length ? existing : [newConversation()];
  });
  const [activeId, setActiveId] = useState<string>(() => convos[0].id);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const active = convos.find((c) => c.id === activeId) ?? convos[0];

  useEffect(() => saveConversations(uid, convos), [uid, convos]);
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
        appendMessage(cs, activeId, {
          role: "assistant",
          content: r.reply,
          replyId: r.reply_message_id ?? undefined,
        }),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function addConversation() {
    const c = newConversation();
    setConvos((cs) => {
      const { kept, evicted } = capConversations([c, ...cs]);
      if (evicted.length) {
        setWarning(
          `已達 ${MAX_CONVERSATIONS} 個對話上限，已刪除最舊的 ${evicted.length} 則。`,
        );
        // best-effort backend cleanup of the evicted sessions
        evicted.forEach((e) => api.deleteSession(e.id).catch(() => {}));
      }
      return kept;
    });
    setActiveId(c.id);
  }

  async function removeConversation(id: string) {
    try {
      await api.deleteSession(id);
    } catch {
      /* ignore: local removal still proceeds */
    }
    setConvos((cs) => {
      const next = cs.filter((c) => c.id !== id);
      const ensured = next.length ? next : [newConversation()];
      if (id === activeId) setActiveId(ensured[0].id);
      return ensured;
    });
  }

  async function rate(replyId: number, rating: number) {
    try {
      const r = await api.sendFeedback(replyId, rating);
      setConvos((cs) => setRating(cs, replyId, r.rating));
    } catch (err) {
      setError(errorMessage(err));
    }
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
            <div
              key={c.id}
              className={`group flex items-center rounded ${
                c.id === activeId ? "bg-gray-100" : "hover:bg-gray-50"
              }`}
            >
              <button
                onClick={() => setActiveId(c.id)}
                className={`block flex-1 truncate px-2 py-1.5 text-left text-sm ${
                  c.id === activeId ? "font-medium" : "text-gray-600"
                }`}
              >
                {c.title}
              </button>
              <button
                aria-label="delete conversation"
                onClick={() => removeConversation(c.id)}
                className="px-2 text-gray-400 opacity-0 hover:text-red-600 group-hover:opacity-100"
              >
                ✕
              </button>
            </div>
          ))}
        </aside>

        <main className="flex min-h-0 flex-1 flex-col">
          {warning && (
            <div className="flex items-center justify-between bg-amber-50 px-4 py-2 text-sm text-amber-800">
              <span>{warning}</span>
              <button
                onClick={() => setWarning(null)}
                className="text-amber-600 hover:text-amber-900"
              >
                ✕
              </button>
            </div>
          )}
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {active.messages.length === 0 && (
              <p className="mt-8 text-center text-sm text-gray-400">
                Ask anything…
              </p>
            )}
            {active.messages.map((m, i) => (
              <MessageBubble key={i} message={m} onFeedback={rate} />
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
