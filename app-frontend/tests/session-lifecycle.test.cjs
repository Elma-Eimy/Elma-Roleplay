const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

function message(id, content = String(id)) {
  return { id, content, role: "user", created_at: "2026-10-20", emotion_tag: null, affection_change: null };
}

function chatFixture(history, stream = async () => {}) {
  setActivePinia(createPinia());
  const personaUpdates = [];
  const load = createLoader({ mocks: {
    "@/api/sessions": { getSessionHistory: history },
    "@/api/chat": { sendMessageStream: stream },
    "@/api/config": {},
    "./personaStore": { usePersonaStore: () => ({ userNickname: "用户", applyAffectionChange: (...args) => personaUpdates.push(args) }) },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": { useChatSettingsStore: () => ({ clearParameters() {}, activateSession() {}, requestGeneration() { return { thinking_mode: "inherit" }; }, $reset() {}, useReasoning: false }) },
  } });
  return { store: load("store/chatStore.ts").useChatStore(), personaUpdates };
}

test("an older history response cannot overwrite a newly selected session", async () => {
  const a = deferred(), b = deferred();
  const { store } = chatFixture((id) => id === 1 ? a.promise : b.promise);
  const first = store.loadHistory(1);
  const second = store.loadHistory(2);
  b.resolve({ messages: [message(22)] }); await second;
  a.resolve({ messages: [message(11)] }); await first;
  assert.equal(store.activeSessionId, 2);
  assert.deepEqual(store.messages.map((m) => m.id), [22]);
});

test("an older history failure does not clear the new session's loading state or set its error", async () => {
  const a = deferred(), b = deferred();
  const { store } = chatFixture((id) => id === 1 ? a.promise : b.promise);
  const first = store.loadHistory(1);
  const second = store.loadHistory(2);
  a.reject(new Error("old request failed")); await first;
  assert.equal(store.isLoading, true);
  assert.equal(store.errorMessage, null);
  b.resolve({ messages: [] }); await second;
  assert.equal(store.isLoading, false);
});

test("reset invalidates unfinished history requests", async () => {
  const response = deferred();
  const { store } = chatFixture(() => response.promise);
  const pending = store.loadHistory(1);
  store.$reset();
  response.resolve({ messages: [message(11)] }); await pending;
  assert.equal(store.activeSessionId, null);
  assert.equal(store.messages.length, 0);
  assert.equal(store.isLoading, false);
});

test("pagination from the previous session cannot prepend old messages", async () => {
  const response = deferred();
  const { store } = chatFixture(() => response.promise);
  store.setActiveSession(1); store.setHistory([message(11)]);
  const pending = store.loadMoreHistory();
  store.setActiveSession(2); store.setHistory([message(22)]);
  response.resolve({ messages: [message(5)] });
  assert.equal(await pending, false);
  assert.deepEqual(store.messages.map((m) => m.id), [22]);
});

test("switching sessions cancels the old stream and ignores all its late callbacks", async () => {
  const transport = deferred(), history = deferred();
  let callbacks;
  const { store, personaUpdates } = chatFixture(() => history.promise, (...args) => {
    callbacks = args;
    return transport.promise;
  });
  store.setActiveSession(1);
  const sending = store.sendChatMessage(1, "hello");
  const loading = store.loadHistory(2);
  assert.equal(callbacks[5].cancelled, true);
  callbacks[1]("old chunk");
  callbacks[2]({ affection_score: 99, assistant_message_id: 10 });
  callbacks[3](new Error("old failure"));
  callbacks[4]("old reasoning");
  assert.equal(store.isLoading, true);
  assert.equal(store.errorMessage, null);
  assert.equal(personaUpdates.length, 0);
  history.resolve({ messages: [message(22)] }); await loading;
  transport.resolve(); await sending;
  assert.deepEqual(store.messages.map((m) => m.id), [22]);
});

test("a stale App completion with no active placeholder cannot mutate persona or loading", () => {
  const { store, personaUpdates } = chatFixture(async () => ({ messages: [] }));
  store.setActiveSession(2); store.isLoading = true;
  store.completeStream("old-placeholder", { affection_score: 99 });
  store.failStream("old-placeholder", "old error");
  assert.equal(store.isLoading, true);
  assert.equal(store.errorMessage, null);
  assert.equal(personaUpdates.length, 0);
});

function personaFixture(getSession, getCharacter) {
  setActivePinia(createPinia());
  return createLoader({ mocks: {
    "@/api/sessions": { getSession }, "@/api/characters": { getCharacter },
  }, globals: { uni: { getStorageSync: () => ({}), setStorageSync() {} } } })("store/personaStore.ts").usePersonaStore();
}

test("a late character lookup cannot replace the current session's character or persona", async () => {
  const a = deferred(), b = deferred();
  const store = personaFixture(async (id) => ({ character: { id }, persona: { id } }), (id) => id === 1 ? a.promise : b.promise);
  const first = store.loadSessionDetail(1); await Promise.resolve();
  const second = store.loadSessionDetail(2); await Promise.resolve();
  b.resolve({ id: 2, name: "new character" }); await second;
  a.resolve({ id: 1, name: "old character" }); await first;
  assert.equal(store.activeCharacter.id, 2);
  assert.equal(store.currentPersona.id, 2);
});

test("leaving the page invalidates an unfinished persona request", async () => {
  const session = deferred();
  let characterQueries = 0;
  const store = personaFixture(() => session.promise, async () => { characterQueries++; });
  const pending = store.loadSessionDetail(1);
  store.cancelSessionLoad();
  session.resolve({ character: { id: 1 }, persona: { id: 1 } }); await pending;
  assert.equal(store.isLoadingPersona, false);
  assert.equal(store.activeCharacter, null);
  assert.equal(characterQueries, 0);
});
