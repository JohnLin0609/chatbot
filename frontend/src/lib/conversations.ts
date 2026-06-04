export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

const KEY = "cc_conversations";

function newId(): string {
  // conversation id = chat channel id, not security-sensitive
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().slice(0, 8);
  }
  return Math.random().toString(36).slice(2, 10);
}

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Conversation[]) : [];
  } catch {
    return [];
  }
}

export function saveConversations(cs: Conversation[]): void {
  localStorage.setItem(KEY, JSON.stringify(cs));
}

export function newConversation(): Conversation {
  return { id: newId(), title: "New chat", messages: [] };
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
