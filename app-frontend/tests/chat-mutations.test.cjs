const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { effectScope, ref } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const plain = value => JSON.parse(JSON.stringify(value));
const message = () => ({ id: 10, role: "assistant", content: "original", created_at: "2026-10-26",
  candidates: [{ id: 10, content: "original" }, { id: 11, content: "alternative", reasoning_content: "thinking" }], active_index: 0 });

function fixture(api = {}, { platform = "H5", stream = async () => {}, ui = {} } = {}) {
  setActivePinia(createPinia());
  const updates = [], toasts = [], timers = [];
  let endpoint = "https://server-a.invalid";
  const persona = { userNickname: "user", loadSessionDetail: async () => {}, applyAffectionChange: (...args) => updates.push(args) };
  const settings = { clearParameters() {}, activateSession() {}, requestGeneration: () => ({}), $reset() {} };
  const load = createLoader({ platform, mocks: {
    "@/api/sessions": { getSessionHistory: async () => ({ messages: [] }), ...api },
    "@/api/chat": { sendMessageStream: stream },
    "@/api/config": { getBaseUrl: () => endpoint, getSavedApiKey: () => "" },
    "./personaStore": { usePersonaStore: () => persona }, "@/store/personaStore": { usePersonaStore: () => persona },
    "./chatSettingsStore": { useChatSettingsStore: () => settings }, "@/store/chatSettingsStore": { useChatSettingsStore: () => settings },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {}, playMessageTTS() {} }) },
  }, globals: { uni: { showToast: value => toasts.push(value), ...ui },
    setTimeout(callback) { timers.push(callback); return timers.length; }, clearTimeout() {} } });
  const store = load("store/chatStore.ts").useChatStore();
  store.setActiveSession(1); store.setHistory([message()]);
  const scope = effectScope();
  const sessionId = ref(1);
  const actions = scope.run(() => load("composables/useChatMessageActions.ts").useChatMessageActions(sessionId, async () => {}));
  return { store, actions, sessionId, updates, toasts, timers, load,
    changeServer() { endpoint = "https://server-b.invalid"; load("utils/connectionEvents.ts").notifyServerChange(); },
    dispose() { scope.stop(); store.$dispose(); } };
}

const mutations = [
  ["edit", "updateMessage", store => store.editMessage(10, "edited")],
  ["delete", "deleteMessage", store => store.deleteMessageById(10)],
  ["candidate", "switchCandidate", store => store.switchActiveCandidate(10, 11)],
];
for (const [name, api, invoke] of mutations) {
  for (const transition of ["session", "reset", "server"]) {
    for (const outcome of ["success", "failure"]) {
      test(`${name} ${outcome} cannot write after ${transition} invalidation`, async t => {
        const pending = deferred();
        const f = fixture({ [api]: () => pending.promise }); t.after(f.dispose);
        const action = invoke(f.store);
        if (transition === "server") f.changeServer();
        else if (transition === "reset") f.store.$reset();
        f.store.setActiveSession(2); f.store.setHistory([message()]);
        f.store.isLoading = true; f.store.errorMessage = "new story";
        const before = plain(f.store.messages);
        if (outcome === "success") pending.resolve({ affection_score: 99, current_mood: "old" });
        else pending.reject(new Error("old failure"));
        assert.equal((await action).status, "stale");
        assert.deepEqual(plain(f.store.messages), before);
        assert.equal(f.store.isLoading, true);
        assert.equal(f.store.errorMessage, "new story");
        assert.equal(f.updates.length, 0);
      });
    }
  }
  test(`${name} failure preserves unrelated loading and returns a visible error`, async t => {
    const f = fixture({ [api]: async () => { throw new Error("operation failed"); } }); t.after(f.dispose);
    f.store.isLoading = true;
    const result = await invoke(f.store);
    assert.equal(result.status, "error"); assert.equal(result.message, "operation failed");
    assert.equal(f.store.isLoading, true);
    assert.equal(f.store.messages[0].content, "original");
  });
}

test("successful current edits, candidate changes and sibling deletion retain existing behavior", async t => {
  const f = fixture({ updateMessage: async () => ({}), switchCandidate: async () => ({ affection_score: 35, current_mood: "calm" }),
    deleteMessage: async () => ({ affection_score: 30, current_mood: "neutral" }) }); t.after(f.dispose);
  assert.equal((await f.store.editMessage(10, "edited")).status, "success");
  assert.equal(f.store.messages[0].content, "edited");
  assert.equal((await f.store.switchActiveCandidate(10, 11)).status, "success");
  assert.equal(f.store.messages[0].id, 11);
  assert.equal((await f.store.deleteMessageById(11)).status, "success");
  assert.equal(f.store.messages[0].id, 10);
  assert.equal(f.updates.at(-1)[1], 30);
});

test("failed edits preserve the editor and draft, then a successful retry closes it", async t => {
  let calls = 0;
  const f = fixture({ updateMessage: async () => { if (++calls === 1) throw new Error("save failed"); } }); t.after(f.dispose);
  f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "draft";
  await f.actions.saveEdit();
  assert.equal(f.actions.editingMessageId.value, 10);
  assert.equal(f.actions.editMessageContent.value, "draft");
  assert.equal(f.actions.editError.value, "save failed");
  assert.equal(f.actions.isSavingEdit.value, false);
  await f.actions.saveEdit();
  assert.equal(f.actions.editingMessageId.value, null);
  assert.equal(f.actions.editMessageContent.value, "");
  assert.equal(f.store.messages[0].content, "draft");
});

test("duplicate saves are blocked and a cancelled save cannot close a reopened editor", async t => {
  const pending = deferred(); let calls = 0;
  const f = fixture({ updateMessage: () => { calls++; return pending.promise; } }); t.after(f.dispose);
  f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "old draft";
  const first = f.actions.saveEdit(); await f.actions.saveEdit();
  assert.equal(calls, 1);
  f.actions.cancelEdit(); f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "new draft";
  pending.resolve(); await first;
  assert.equal(f.actions.editingMessageId.value, 10);
  assert.equal(f.actions.editMessageContent.value, "new draft");
});

for (const outcome of ["success", "failure"]) {
  test(`an old edit ${outcome} cannot finish a newer save or replace its draft`, async t => {
    const old = deferred(), recent = deferred(); let calls = 0;
    const f = fixture({ updateMessage: () => ++calls === 1 ? old.promise : recent.promise }); t.after(f.dispose);
    f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "old draft";
    const first = f.actions.saveEdit();
    f.actions.cancelEdit(); f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "new draft";
    const second = f.actions.saveEdit();
    if (outcome === "success") old.resolve(); else old.reject(new Error("old edit failed"));
    await first;
    assert.equal(f.actions.isSavingEdit.value, true);
    assert.equal(f.actions.editMessageContent.value, "new draft");
    assert.equal(f.actions.editError.value, "");
    recent.resolve(); await second;
    assert.equal(f.actions.isSavingEdit.value, false);
    assert.equal(f.actions.editingMessageId.value, null);
    assert.equal(f.store.messages[0].content, "new draft");
  });
}

test("old action sheets and delete confirmations cannot operate on a replacement story", async t => {
  let sheet, modal, deletes = 0;
  const f = fixture({ deleteMessage: async () => { deletes++; return {}; } }, { ui: {
    showActionSheet: value => { sheet = value; }, showModal: value => { modal = value; },
  } }); t.after(f.dispose);
  f.actions.onMessageLongPress(message());
  const oldSheet = sheet;
  oldSheet.success({ tapIndex: oldSheet.itemList.indexOf("删除此消息") }); oldSheet.complete();
  f.store.setActiveSession(2); f.sessionId.value = 2;
  await modal.success({ confirm: true });
  oldSheet.success({ tapIndex: oldSheet.itemList.indexOf("编辑消息") });
  assert.equal(deletes, 0);
  assert.equal(f.actions.editingMessageId.value, null);
});

for (const transition of ["session", "server", "dispose"]) {
  test(`editing drafts are invalidated on ${transition} changes`, async t => {
    const pending = deferred(); const f = fixture({ updateMessage: () => pending.promise }); t.after(f.dispose);
    f.actions.editingMessageId.value = 10; f.actions.editMessageContent.value = "draft";
    const action = f.actions.saveEdit();
    if (transition === "session") { f.store.setActiveSession(2); f.sessionId.value = 2; }
    else if (transition === "server") f.changeServer();
    else f.dispose();
    pending.reject(new Error("late save failure")); await action;
    assert.equal(f.actions.editingMessageId.value, null);
    assert.equal(f.actions.editError.value, "");
    assert.equal(f.actions.isSavingEdit.value, false);
  });
}

for (const platform of ["H5", "MP-WEIXIN", "APP-PLUS"]) {
  test(`server changes stop ${platform} streams and pending recovery without another POST`, async t => {
    const pending = deferred(); let callbacks, reads = 0, posts = 0;
    const f = fixture({ getSessionHistory: async () => { reads++; return { messages: [], is_generating: true }; } },
      { platform, stream: (...args) => { posts++; callbacks = args; return pending.promise; } }); t.after(f.dispose);
    const sending = f.store.sendChatMessage(1, "question"); await flush();
    if (platform === "APP-PLUS") {
      const request = f.store.activeStreamRequest;
      const bridgeScope = effectScope(); t.after(() => bridgeScope.stop());
      const bridge = bridgeScope.run(() => f.load("composables/useChatStreamBridge.ts").useChatStreamBridge());
      bridge.onBridgeMessage({ detail: { ...request, type: "error", error: "disconnected" } });
    } else callbacks[3](new Error("disconnected"));
    assert.equal(f.timers.length, 1);
    f.changeServer();
    assert.equal(f.store.activeSessionId, null); assert.equal(f.store.isLoading, false);
    assert.equal(f.store.activeStreamRequest, null); assert.equal(f.store.messages.length, 0);
    f.timers.shift()(); await flush();
    assert.equal(reads, 0);
    if (callbacks) { callbacks[1]("late"); callbacks[2]({ affection_score: 99 }); }
    pending.resolve(); await sending;
    assert.equal(f.updates.length, 0); assert.equal(f.store.messages.length, 0);
    assert.equal(posts, platform === "APP-PLUS" ? 0 : 1);
  });
}
