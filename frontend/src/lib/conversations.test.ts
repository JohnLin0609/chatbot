import {
  appendMessage,
  capConversations,
  loadConversations,
  newConversation,
  saveConversations,
  setRating,
} from "./conversations";

beforeEach(() => localStorage.clear());

it("new/save/load round-trip (per user)", () => {
  const c = newConversation();
  saveConversations(1, [c]);
  const loaded = loadConversations(1);
  expect(loaded).toHaveLength(1);
  expect(loaded[0].id).toBe(c.id);
});

it("isolates conversations per user", () => {
  saveConversations(1, [newConversation()]);
  // a different user starts empty — no leak across accounts
  expect(loadConversations(2)).toEqual([]);
  // user 1 still has theirs
  expect(loadConversations(1)).toHaveLength(1);
});

it("append adds a message and titles from the first user turn", () => {
  const c = newConversation();
  const cs = appendMessage([c], c.id, {
    role: "user",
    content: "What is the refund policy?",
  });
  expect(cs[0].messages).toHaveLength(1);
  expect(cs[0].title).toBe("What is the refund policy?");
});

it("append does not retitle on later turns", () => {
  let cs = [newConversation()];
  const id = cs[0].id;
  cs = appendMessage(cs, id, { role: "user", content: "first message here" });
  cs = appendMessage(cs, id, { role: "assistant", content: "a reply" });
  expect(cs[0].title).toBe("first message here");
  expect(cs[0].messages).toHaveLength(2);
});

it("caps at 20, evicting the oldest", () => {
  const cs = Array.from({ length: 21 }, (_, i) => ({
    ...newConversation(),
    createdAt: i, // i=0 is oldest
  }));
  const { kept, evicted } = capConversations(cs);
  expect(kept).toHaveLength(20);
  expect(evicted).toHaveLength(1);
  expect(evicted[0].createdAt).toBe(0); // the oldest got evicted
  expect(kept.some((c) => c.createdAt === 0)).toBe(false);
});

it("does not evict at or under the cap", () => {
  const cs = Array.from({ length: 20 }, () => newConversation());
  const { kept, evicted } = capConversations(cs);
  expect(kept).toHaveLength(20);
  expect(evicted).toHaveLength(0);
});

it("setRating updates the matching assistant message by replyId", () => {
  const c = {
    ...newConversation(),
    messages: [
      { role: "assistant" as const, content: "a", replyId: 42, rating: 0 },
    ],
  };
  const cs = setRating([c], 42, 1);
  expect(cs[0].messages[0].rating).toBe(1);
});

it("loadConversations returns [] on bad json", () => {
  localStorage.setItem("cc_conversations_1", "not-json");
  expect(loadConversations(1)).toEqual([]);
});
