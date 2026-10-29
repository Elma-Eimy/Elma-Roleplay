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

test("reading preferences normalize invalid values and persist across story resets", () => {
  const plain = value => JSON.parse(JSON.stringify(value));
  assert.deepEqual(plain(display.normalizeReadingPrefs({ fontScale: "lg", lineSpacing: "compact", bubbleStyle: "novel", colorTheme: "dark" })),
    { fontScale: "lg", lineSpacing: "compact", bubbleStyle: "novel", colorTheme: "dark" });
  assert.deepEqual(plain(display.normalizeReadingPrefs({ fontScale: "huge", lineSpacing: null, bubbleStyle: 123, colorTheme: "neon" })),
    plain(display.DEFAULT_READING_PREFS));

  setActivePinia(createPinia());
  const storage = new Map([["chat_reading_prefs_v1", JSON.stringify({ fontScale: "xl", bubbleStyle: "novel", colorTheme: "dark" })]]);
  const load = createLoader({
    mocks: {
      "@/api/config": { getBaseUrl: () => "https://one.test" },
      "@/api/settings": { getSettings: async () => ({}), DEFAULT_SETTINGS: { default_chat_model: "m", model_profiles: [], model_catalog: [], reasoning_mode: false, reasoning_effort: "high" } },
    },
    globals: { uni: { getStorageSync: key => storage.get(key), setStorageSync: (key, val) => storage.set(key, val) } },
  });
  const settings = load("store/chatSettingsStore.ts").useChatSettingsStore();
  assert.deepEqual(plain(settings.readingPrefs), { fontScale: "xl", lineSpacing: "comfortable", bubbleStyle: "novel", colorTheme: "dark" });
  settings.updateReadingPrefs({ lineSpacing: "compact", fontScale: "bad" });
  assert.deepEqual(plain(settings.readingPrefs), { fontScale: "md", lineSpacing: "compact", bubbleStyle: "novel", colorTheme: "dark" });
  settings.$reset();
  assert.equal(settings.readingPrefs.bubbleStyle, "novel", "device reading prefs survive session reset");
  assert.deepEqual(JSON.parse(storage.get("chat_reading_prefs_v1")), plain(settings.readingPrefs));
});

test("immersive header fades on downward scroll and restores near the top or on upward scroll", () => {
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: false, scrollTop: 200, previousScrollTop: 100, isImmersive: false }), false);
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: false, scrollTop: 50, previousScrollTop: 0, isImmersive: true }), false);
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: false, scrollTop: 200, previousScrollTop: 150, isImmersive: true }), true);
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: true, scrollTop: 205, previousScrollTop: 200, isImmersive: true }), true);
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: true, scrollTop: 160, previousScrollTop: 205, isImmersive: true }), false);
  assert.equal(display.shouldFadeHeaderOnScroll({ currentHidden: true, scrollTop: 40, previousScrollTop: 30, isImmersive: true }), false);
});

test("custom action sheet state exposes items and invalidates on session or server change", t => {
  setActivePinia(createPinia());
  const { ref } = require("vue");
  let server = "https://one.test", modals = 0;
  const load = createLoader({
    mocks: {
      "@/api/sessions": { getSessionHistory: async () => ({ messages: [] }), createSession: async () => ({ session_id: 2 }) },
      "@/api/chat": { sendMessageStream: async () => {} },
      "@/api/config": { getBaseUrl: () => server, getSavedApiKey: () => "" },
      "./personaStore": { usePersonaStore: () => ({ userNickname: "u", activeCharacter: { id: 1, name: "Luna" }, loadSessionDetail: async () => {}, applyAffectionChange() {} }) },
      "@/store/personaStore": { usePersonaStore: () => ({ userNickname: "u", activeCharacter: { id: 1, name: "Luna" }, loadSessionDetail: async () => {}, applyAffectionChange() {} }) },
      "./chatSettingsStore": { useChatSettingsStore: () => ({ clearParameters() {}, activateSession() {}, inheritSession() {}, requestGeneration: () => ({}), $reset() {} }) },
      "@/store/chatSettingsStore": { useChatSettingsStore: () => ({ clearParameters() {}, activateSession() {}, inheritSession() {}, requestGeneration: () => ({}), $reset() {} }) },
      "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {}, playMessageTTS() {} }) },
    },
    globals: { uni: { showModal: () => { modals++; }, showToast() {} } },
  });
  const store = load("store/chatStore.ts").useChatStore();
  store.setActiveSession(1);
  const first = { id: 1, role: "assistant", content: "earlier", created_at: "2026-10-29" };
  const latest = { id: 2, role: "assistant", content: "latest", created_at: "2026-10-29" };
  store.setHistory([first, latest]);
  const sessionId = ref(1);
  const scope = effectScope();
  const actions = scope.run(() => load("composables/useChatMessageActions.ts").useChatMessageActions(sessionId, async () => {}));
  t.after(() => { scope.stop(); store.$dispose(); });

  actions.onMessageLongPress(first);
  assert.equal(actions.actionSheetItems.value.some(item => item.key === "regenerate"), false);
  actions.closeActionSheet();

  actions.onMessageLongPress(latest);
  assert.equal(actions.actionSheetItems.value.some(item => item.key === "regenerate"), true);
  assert.equal(actions.actionSheetItems.value.find(item => item.key === "delete").danger, true);

  // 切服后旧面板自动关闭，即使调用 selectActionSheetItem 也不会触发操作
  server = "https://two.test";
  load("utils/connectionEvents.ts").notifyServerChange();
  assert.equal(actions.actionSheetMessage.value, null);
  actions.selectActionSheetItem("delete");
  assert.equal(modals, 0);
});

test("time dividers appear only across 30-minute gaps and format relative dates", () => {
  const now = new Date(2026, 9, 29, 18, 0, 0);
  const iso = (y, m, d, hh, mm) => new Date(y, m - 1, d, hh, mm, 0).toISOString();
  assert.equal(display.formatMessageTimestamp(iso(2026, 10, 29, 9, 5), now), "09:05");
  assert.equal(display.formatMessageTimestamp(iso(2026, 10, 28, 21, 30), now), "昨天 21:30");
  assert.equal(display.formatMessageTimestamp(iso(2026, 10, 12, 8, 0), now), "10-12 08:00");
  assert.equal(display.formatMessageTimestamp(iso(2025, 12, 31, 23, 59), now), "2025-12-31 23:59");
  assert.equal(display.formatMessageTimestamp("invalid", now), "");

  const messages = [
    { created_at: iso(2026, 10, 29, 10, 0) },
    { created_at: iso(2026, 10, 29, 10, 12) },
    { created_at: "not-a-date" },
    { created_at: iso(2026, 10, 29, 10, 45) },
  ];
  assert.deepEqual(Array.from(display.computeTimeDividers(messages, { now })), [null, null, null, "10:45"]);
});

test("render window slicing and bounded LRU cache cap work for long sessions", () => {
  const plain = value => JSON.parse(JSON.stringify(value));
  assert.deepEqual(plain(display.computeRenderWindow(50, 80)), { startIndex: 0, hiddenCount: 0 });
  assert.deepEqual(plain(display.computeRenderWindow(140, 80)), { startIndex: 60, hiddenCount: 60 });

  const cache = display.createBoundedCache(2);
  cache.set("a", 1);
  cache.set("b", 2);
  assert.equal(cache.get("a"), 1); // 刷新 a 的最近访问顺序
  cache.set("c", 3);
  assert.equal(cache.get("b"), undefined);
  assert.equal(cache.get("a"), 1);
  assert.equal(cache.get("c"), 3);
  assert.equal(cache.size, 2);
});
