const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");

const plain = (value) => JSON.parse(JSON.stringify(value));

function createDraftFixture(initialServer = "https://a.invalid") {
  let server = initialServer;
  const storage = new Map();
  const load = createLoader({
    mocks: {
      "@/api/config": { getBaseUrl: () => server },
    },
    globals: {
      uni: {
        getStorageSync: (key) => storage.get(key),
        setStorageSync: (key, value) => storage.set(key, value),
        removeStorageSync: (key) => storage.delete(key),
      },
    },
  });
  return {
    drafts: load("utils/chatDrafts.ts"),
    storage,
    setServer: (next) => {
      server = next;
    },
  };
}

test("chatDrafts persists drafts per server and session kind and removes empty entries", () => {
  const { drafts, storage, setServer } = createDraftFixture("https://a.invalid");

  drafts.saveChatDraft("single", 10, "单聊草稿\n");
  drafts.saveChatDraft("group", 10, "群聊草稿");
  assert.equal(drafts.loadChatDraft("single", 10), "单聊草稿\n");
  assert.equal(drafts.loadChatDraft("group", 10), "群聊草稿");
  assert.deepEqual(plain(drafts.readAllChatDrafts()), {
    "single:10": "单聊草稿\n",
    "group:10": "群聊草稿",
  });

  setServer("https://b.invalid");
  assert.equal(drafts.loadChatDraft("single", 10), "");
  drafts.saveChatDraft("single", 10, "另一台服务器");
  assert.equal(drafts.loadChatDraft("single", 10), "另一台服务器");

  setServer("https://a.invalid");
  assert.equal(drafts.loadChatDraft("single", 10), "单聊草稿\n");
  drafts.saveChatDraft("single", 10, "   \n ");
  assert.equal(drafts.loadChatDraft("single", 10), "");
  assert.equal(drafts.loadChatDraft("group", 10), "群聊草稿");

  drafts.clearChatDraft("group", 10);
  assert.equal(storage.has("chat_drafts_v1:https%3A%2F%2Fa.invalid"), false);
  assert.equal(storage.has("chat_drafts_v1:https%3A%2F%2Fb.invalid"), true);
});

test("chatDrafts ignores invalid session IDs and storage exceptions", () => {
  const { drafts } = createDraftFixture();
  drafts.saveChatDraft("single", 0, "ignored");
  drafts.saveChatDraft("group", -1, "ignored");
  assert.equal(drafts.loadChatDraft("single", 0), "");

  const broken = createLoader({
    mocks: { "@/api/config": { getBaseUrl: () => "https://broken.invalid" } },
    globals: {
      uni: {
        getStorageSync() { throw new Error("read denied"); },
        setStorageSync() { throw new Error("write denied"); },
        removeStorageSync() { throw new Error("remove denied"); },
      },
    },
  })("utils/chatDrafts.ts");

  assert.deepEqual(plain(broken.readAllChatDrafts()), {});
  assert.equal(broken.loadChatDraft("single", 1), "");
  assert.doesNotThrow(() => broken.saveChatDraft("single", 1, "草稿"));
  assert.doesNotThrow(() => broken.clearChatDraft("single", 1));
});

test("mergeHomeStories attaches normalized single and group drafts without overriding preview", () => {
  const { mergeHomeStories } = createLoader()("utils/homeStories.ts");
  const single = {
    id: 5,
    title: "单聊",
    parent_session_id: null,
    created_at: "2026-11-20T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    characterName: "露娜",
    characterAvatar: "/a.png",
    lastMessage: "上一句回复",
    lastMessageTime: "2026-11-20T10:00:00Z",
    unread: false,
  };
  const group = {
    kind: "group",
    session_id: 9,
    title: "群聊",
    user_nickname: "旅人",
    shared_setting: null,
    created_at: "2026-11-20T09:00:00Z",
    updated_at: "2026-11-20T09:00:00Z",
    can_generate: true,
    last_message: { role: "assistant", speaker_name: "甲", content: "历史发言", created_at: "2026-11-20T09:00:00Z" },
    members: [{ persona_id: 1, slot: 1, character: { id: 1, name: "甲", avatar_path: "" }, greeting_content: null }],
  };

  const withDrafts = mergeHomeStories([single], [group], {
    "single:5": "  未发送的\n单聊草稿  ",
    "group:9": "   ",
  });
  assert.equal(withDrafts[0].draft, "未发送的 单聊草稿");
  assert.equal(withDrafts[0].preview, "上一句回复");
  assert.equal(withDrafts[1].draft, "");
  assert.equal(withDrafts[1].preview, "甲: 历史发言");
});
