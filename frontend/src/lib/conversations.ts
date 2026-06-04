export interface Message {
  role: "user" | "assistant";
  content: string;
  replyId?: number; // backend assistant-message id (assistant turns only)
  rating?: number; // this user's 👍/👎 on it: 1 | -1 | 0
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
}

export const MAX_CONVERSATIONS = 20;

// Storage is scoped per user so switching accounts never leaks conversations.
function keyFor(userId: number | string): string {
  return `cc_conversations_${userId}`;
}

function newId(): string {
  // conversation id = chat channel id, not security-sensitive
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().slice(0, 8);
  }
  return Math.random().toString(36).slice(2, 10);
}

export function loadConversations(userId: number | string): Conversation[] {
  try {
    const raw = localStorage.getItem(keyFor(userId));
    return raw ? (JSON.parse(raw) as Conversation[]) : [];
  } catch {
    return [];
  }
}

export function saveConversations(
  userId: number | string,
  cs: Conversation[],
): void {
  localStorage.setItem(keyFor(userId), JSON.stringify(cs));
}

export function newConversation(): Conversation {
  return { id: newId(), title: "New chat", messages: [], createdAt: Date.now() };
}

/** Keep at most `max` conversations, evicting the oldest (by createdAt).
 *  Returns the kept list and the evicted ones (so the caller can delete them
 *  on the backend and warn the user). */
export function capConversations(
  cs: Conversation[],
  max = MAX_CONVERSATIONS,
): { kept: Conversation[]; evicted: Conversation[] } {
  if (cs.length <= max) return { kept: cs, evicted: [] };
  const byOldest = [...cs].sort((a, b) => a.createdAt - b.createdAt);
  const evicted = byOldest.slice(0, cs.length - max);
  const evictedIds = new Set(evicted.map((c) => c.id));
  return { kept: cs.filter((c) => !evictedIds.has(c.id)), evicted };
}

export function appendMessage(
  cs: Conversation[],
  id: string,
  msg: Message,
): Conversation[] {
  return cs.map((c) => {
    if (c.id !== id) return c;
    const firstUserTurn = c.messages.length === 0 && msg.role === "user";
    return {
      ...c,
      title: firstUserTurn ? msg.content.slice(0, 40) : c.title,
      messages: [...c.messages, msg],
    };
  });
}

/** Set the local rating on an assistant message (matched by replyId). */
export function setRating(
  cs: Conversation[],
  replyId: number,
  rating: number,
): Conversation[] {
  return cs.map((c) => ({
    ...c,
    messages: c.messages.map((m) =>
      m.replyId === replyId ? { ...m, rating } : m,
    ),
  }));
}
