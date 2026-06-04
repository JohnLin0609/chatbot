import {
  appendMessage,
  loadConversations,
  newConversation,
  saveConversations,
} from "./conversations";

beforeEach(() => localStorage.clear());

it("new/save/load round-trip", () => {
  const c = newConversation();
  saveConversations([c]);
  const loaded = loadConversations();
  expect(loaded).toHaveLength(1);
  expect(loaded[0].id).toBe(c.id);
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

it("loadConversations returns [] on bad json", () => {
  localStorage.setItem("cc_conversations", "not-json");
  expect(loadConversations()).toEqual([]);
});
