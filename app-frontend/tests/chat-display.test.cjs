const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { effectScope, nextTick } = require("vue");
const { createLoader } = require("./helpers/load-ts.cjs");

const display = createLoader()("utils/chatDisplay.ts");

test("near-bottom detection tolerates unknown viewport and uses the threshold", () => {
  assert.equal(display.isNearBottom({ scrollTop: 0, scrollHeight: 5000, viewportHeight: 0 }), true);
  assert.equal(display.isNearBottom({ scrollTop: 4300, scrollHeight: 5000, viewportHeight: 600 }), true);
  assert.equal(display.isNearBottom({ scrollTop: 4000, scrollHeight: 5000, viewportHeight: 600 }), false);
});

test("only locally created messages play the entry animation", () => {
  assert.equal(display.shouldAnimateMessageEntry("user-1-abc"), true);
  assert.equal(display.shouldAnimateMessageEntry("assistant-1-abc"), true);
  assert.equal(display.shouldAnimateMessageEntry("msg-42"), false);
  assert.equal(display.shouldAnimateMessageEntry(undefined), false);
});

test("latest assistant index skips trailing user messages", () => {
  const roles = ["assistant", "user", "assistant", "user"].map(role => ({ role }));
  assert.equal(display.findLatestAssistantIndex(roles), 2);
  assert.equal(display.findLatestAssistantIndex([{ role: "user" }]), -1);
});

test("thought title shows elapsed seconds only when timing is known", () => {
  assert.equal(display.formatThoughtTitle({ isThinking: true, elapsedMs: 8200 }), "思考中 · 8s");
  assert.equal(display.formatThoughtTitle({ isThinking: true, elapsedMs: 100 }), "思考中 · 1s");
  assert.equal(display.formatThoughtTitle({ isThinking: false, elapsedMs: 12400 }), "已思考 12 秒");
  assert.equal(display.formatThoughtTitle({ isThinking: false, elapsedMs: null }), "已深度思考");
  assert.equal(display.lastNonEmptyLine("first\n\nsecond line\n  \n"), "second line");
});

test("scroll follows new content only while pinned and flags unread otherwise", async () => {
  const scope = effectScope();
  // 生命周期钩子只负责键盘监听与定时器清理，这里脱离组件实例运行。
  const vue = { ...require("vue"), onMounted() {}, onUnmounted() {} };
  const scroll = scope.run(() => createLoader({ mocks: { vue } })("composables/useChatScroll.ts").useChatScroll());
  const viewport = { scrollHeight: 5000, viewportHeight: 600 };

  scroll.updateScrollMetrics({ ...viewport, scrollTop: 1000 });
  assert.equal(scroll.isPinnedToBottom.value, false);
  const before = scroll.scrollTop.value;
  scroll.followNewContent();
  await nextTick();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(scroll.scrollTop.value, before, "reading history must not be pulled to bottom");
  assert.equal(scroll.hasUnreadBelow.value, true);

  scroll.updateScrollMetrics({ ...viewport, scrollTop: 4400 });
  assert.equal(scroll.isPinnedToBottom.value, true);
  assert.equal(scroll.hasUnreadBelow.value, false);

  scroll.updateScrollMetrics({ ...viewport, scrollTop: 0 });
  scroll.pinToBottom();
  await nextTick();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(scroll.isPinnedToBottom.value, true);
  assert.notEqual(scroll.scrollTop.value, before);
  scope.stop();
});

function storeFixture() {
  setActivePinia(createPinia());
  const persona = { userNickname: "user", loadSessionDetail: async () => {}, applyAffectionChange() {} };
  const settings = { clearParameters() {}, activateSession() {}, requestGeneration: () => ({}), $reset() {} };
  const load = createLoader({ mocks: {
    "@/api/sessions": { getSessionHistory: async () => ({ messages: [] }) },
    "@/api/chat": { sendMessageStream: async () => {} },
    "@/api/config": { getBaseUrl: () => "https://server.invalid", getSavedApiKey: () => "" },
    "./personaStore": { usePersonaStore: () => persona }, "@/store/personaStore": { usePersonaStore: () => persona },
    "./chatSettingsStore": { useChatSettingsStore: () => settings }, "@/store/chatSettingsStore": { useChatSettingsStore: () => settings },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {}, playMessageTTS() {} }) },
  }, globals: { uni: { showToast() {} } } });
  const store = load("store/chatStore.ts").useChatStore();
  store.setActiveSession(1);
  return store;
}

test("discarding a failed message only removes local unsent user messages", t => {
  const store = storeFixture(); t.after(() => store.$dispose());
  store.setHistory([{ id: 5, role: "user", content: "saved", created_at: "2026-10-29" }]);
  store.messages[0].status = "error";
  store.appendMessage({ id: -1, clientId: "user-1", role: "user", content: "lost words", created_at: "2026-10-29", status: "error" });
  store.errorMessage = "failed";

  assert.equal(store.discardFailedMessage("msg-5"), null, "persisted messages stay");
  store.isLoading = true;
  assert.equal(store.discardFailedMessage("user-1"), null, "no change while generating");
  store.isLoading = false;
  assert.equal(store.discardFailedMessage("user-1"), "lost words");
  assert.deepEqual(store.messages.map(message => message.clientId), ["msg-5"]);
  assert.equal(store.errorMessage, null);
  assert.equal(store.discardFailedMessage("user-1"), null);
});
