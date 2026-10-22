const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

function message(id, content = String(id)) {
  return { id, content, role: "user", created_at: "2026-10-20", emotion_tag: null, affection_change: null };
}

function chatFixture(history, stream = async () => {}, options = {}) {
  setActivePinia(createPinia());
  const personaUpdates = [];
  const load = createLoader({ ...options, mocks: {
    "@/api/sessions": { getSessionHistory: history },
    "@/api/chat": { sendMessageStream: stream },
    "@/api/config": { getBaseUrl: () => "https://example.invalid", getSavedApiKey: () => "" },
    "./personaStore": { usePersonaStore: () => ({ userNickname: "用户", loadSessionDetail: async () => {}, applyAffectionChange: (...args) => personaUpdates.push(args) }) },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": { useChatSettingsStore: () => ({ clearParameters() {}, activateSession() {}, requestGeneration: options.requestGeneration || (() => ({ thinking_mode: "inherit" })), $reset() {}, useReasoning: false }) },
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
  await Promise.resolve();
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

test("loadHistory polls pending background generation and stops on session change", async () => {
  let callCount = 0;
  let personaRefreshed = 0;
  setActivePinia(createPinia());
  const load = createLoader({ mocks: {
    "@/api/sessions": {
      getSessionHistory: async (id) => {
        callCount++;
        if (callCount === 1) {
          return { session_id: id, messages: [message(1, "用户问题")], is_generating: true };
        }
        return {
          session_id: id,
          messages: [
            message(1, "用户问题"),
            { id: 2, role: "assistant", content: "后台生成的回复", created_at: "2026-10-20" },
          ],
          is_generating: false,
        };
      },
    },
    "@/api/chat": { sendMessageStream: async () => {} },
    "@/api/config": { getBaseUrl: () => "https://example.invalid" },
    "./personaStore": {
      usePersonaStore: () => ({
        userNickname: "用户",
        applyAffectionChange: () => {},
        loadSessionDetail: async () => { personaRefreshed++; },
      }),
    },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": {
      useChatSettingsStore: () => ({
        clearParameters() {},
        activateSession() {},
        requestGeneration() { return { thinking_mode: "inherit" }; },
        $reset() {},
        useReasoning: false,
      }),
    },
  } });

  const store = load("store/chatStore.ts").useChatStore();
  await store.loadHistory(1);

  // 初次加载后应有用户消息与流式占位符，且处于 loading 状态
  assert.equal(store.isLoading, true);
  assert.equal(store.messages.length, 2);
  assert.equal(store.messages[1].status, "streaming");

  // 等待轮询定时器触发第一次拉取
  await new Promise((r) => setTimeout(r, 1300));

  // 轮询成功后，消息更新为完成状态，persona 刷新
  assert.equal(store.isLoading, false);
  assert.equal(store.messages.length, 2);
  assert.equal(store.messages[1].role, "assistant");
  assert.equal(store.messages[1].content, "后台生成的回复");
  assert.equal(personaRefreshed, 1);
});

test("regeneration keeps polling while is_generating=true and updates when complete", async () => {
  let callCount = 0;
  let personaRefreshed = 0;
  setActivePinia(createPinia());
  const oldAssistant = {
    id: 10,
    role: "assistant",
    content: "旧回复",
    candidates: [{ id: 10, content: "旧回复" }],
    active_index: 0,
    created_at: "2026-10-20",
  };
  const newAssistant = {
    id: 11,
    role: "assistant",
    content: "新重新生成的回复",
    candidates: [
      { id: 10, content: "旧回复" },
      { id: 11, content: "新重新生成的回复" },
    ],
    active_index: 1,
    created_at: "2026-10-20",
  };

  const load = createLoader({ mocks: {
    "@/api/sessions": {
      getSessionHistory: async (id) => {
        callCount++;
        // 第一次和第二次：虽然末尾已经有 assistant 消息，但 is_generating 仍为 true
        if (callCount <= 2) {
          return {
            session_id: id,
            messages: [message(1, "用户问题"), oldAssistant],
            is_generating: true,
          };
        }
        // 第三次：生成完成，is_generating 变为 false，新候选已入库
        return {
          session_id: id,
          messages: [message(1, "用户问题"), newAssistant],
          is_generating: false,
        };
      },
    },
    "@/api/chat": { sendMessageStream: async () => {} },
    "@/api/config": { getBaseUrl: () => "https://example.invalid" },
    "./personaStore": {
      usePersonaStore: () => ({
        userNickname: "用户",
        applyAffectionChange: () => {},
        loadSessionDetail: async () => { personaRefreshed++; },
      }),
    },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": {
      useChatSettingsStore: () => ({
        clearParameters() {},
        activateSession() {},
        requestGeneration() { return { thinking_mode: "inherit" }; },
        $reset() {},
        useReasoning: false,
      }),
    },
  } });

  const store = load("store/chatStore.ts").useChatStore();
  await store.loadHistory(1);

  // 初始加载：因 is_generating 为 true，即使末尾有 assistant，也绝不结束，应显示占位符
  assert.equal(store.isLoading, true);
  assert.equal(store.messages[store.messages.length - 1].status, "streaming");

  // 等待第一轮轮询触发（仍返回 is_generating=true）
  await new Promise((r) => setTimeout(r, 1300));
  assert.equal(store.isLoading, true);
  assert.equal(store.messages[store.messages.length - 1].status, "streaming");

  // 等待第二轮轮询触发（返回 is_generating=false 且带新候选）
  await new Promise((r) => setTimeout(r, 1300));
  assert.equal(store.isLoading, false);
  const lastMsg = store.messages[store.messages.length - 1];
  assert.equal(lastMsg.role, "assistant");
  assert.equal(lastMsg.content, "新重新生成的回复");
  assert.equal(lastMsg.candidates.length, 2);
  assert.equal(personaRefreshed, 1);
});

test("network interruption during stream recovers via polling without marking user message as error", async () => {
  let callCount = 0;
  setActivePinia(createPinia());

  const load = createLoader({ mocks: {
    "@/api/sessions": {
      getSessionHistory: async (id) => {
        callCount++;
        if (callCount === 1) {
          // 首次探活：后台正在生成中
          return {
            session_id: id,
            messages: [message(100, "网络中断时的提问")],
            is_generating: true,
          };
        }
        // 轮询后：后台完成落库
        return {
          session_id: id,
          messages: [
            message(100, "网络中断时的提问"),
            { id: 101, role: "assistant", content: "断网自愈成功拉取的回复", created_at: "2026-10-20" },
          ],
          is_generating: false,
        };
      },
    },
    "@/api/chat": {
      sendMessageStream: async (_params, _onChunk, _onDone, onError) => {
        // 模拟流式传输过程中发生网络错误
        setTimeout(() => onError(new Error("网络连接失败，请重试")), 50);
      },
    },
    "@/api/config": { getBaseUrl: () => "https://example.invalid" },
    "./personaStore": {
      usePersonaStore: () => ({
        userNickname: "用户",
        applyAffectionChange: () => {},
        loadSessionDetail: async () => {},
      }),
    },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": {
      useChatSettingsStore: () => ({
        clearParameters() {},
        activateSession() {},
        requestGeneration() { return { thinking_mode: "inherit" }; },
        $reset() {},
        useReasoning: false,
      }),
    },
  } });

  const store = load("store/chatStore.ts").useChatStore();
  store.setActiveSession(1);
  await store.sendChatMessage(1, "网络中断时的提问");

  // 发送后发生流式网络错误，但此时不应立即标红用户消息，而是转入自愈轮询
  const userMsg = store.messages.find((m) => m.content === "网络中断时的提问");
  assert.notEqual(userMsg.status, "error");
  assert.equal(store.isLoading, true);

  // 等待轮询自愈完成
  await new Promise((r) => setTimeout(r, 2700));

  // 恢复完成：状态变为正常完成，拉取到完整回复
  assert.equal(store.isLoading, false);
  const assistantMsg = store.messages.find((m) => m.role === "assistant");
  assert.ok(assistantMsg);
  assert.equal(assistantMsg.content, "断网自愈成功拉取的回复");
  assert.equal(store.errorMessage, null);
});

function recoveryFixture(history, platform = "H5") {
  const timers = [];
  const fixture = chatFixture(history, async (_params, _chunk, _done, error) => {
    error(new Error("model or transport failed"));
  }, { platform, globals: {
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
  } });
  return { ...fixture, async tick() {
    assert.ok(timers.length, "expected a recovery timer");
    timers.shift()();
    for (let i = 0; i < 12; i++) await Promise.resolve();
  } };
}

test("a failed new turn cannot reuse the previous assistant and retains the failed question", async () => {
  const history = [message(1, "old question"), { ...message(2, "old answer"), role: "assistant" }];
  const { store, tick } = recoveryFixture(async () => ({ messages: history, is_generating: false }));
  store.setActiveSession(1); store.setHistory(history);
  await store.sendChatMessage(1, "new question");
  await tick();
  assert.equal(store.errorMessage, "model or transport failed");
  assert.equal(store.isLoading, false);
  assert.equal(store.messages.at(-1).content, "new question");
  assert.equal(store.messages.at(-1).status, "error");
  store.$reset();
});

test("failed regeneration restores the original candidate and does not accept an older inactive candidate", async () => {
  const history = [message(1), { ...message(2, "original"), role: "assistant", candidates: [
    { id: 2, content: "original" }, { id: 5, content: "older inactive candidate" },
  ] }];
  const { store, tick } = recoveryFixture(async () => ({
    messages: [message(1), { ...message(5, "older inactive candidate"), role: "assistant" }], is_generating: false,
  }));
  store.setActiveSession(1); store.setHistory(history);
  await store.regenerateChatMessage(1);
  await tick();
  assert.equal(store.errorMessage, "model or transport failed");
  assert.equal(store.messages.at(-1).status, "done");
  assert.equal(store.isLoading, false);
  store.$reset();
});

test("reopening a pending turn removes a user message deleted by worker abort", async () => {
  let reads = 0;
  const { store, tick } = recoveryFixture(async () => ++reads === 1
    ? { messages: [message(1)], is_generating: true }
    : { messages: [], is_generating: false });
  await store.loadHistory(1);
  await tick();
  assert.deepEqual(store.messages, []);
  assert.ok(store.errorMessage);
  assert.equal(store.isLoading, false);
  store.$reset();
});

test("recovery continues past 150 polls while the backend is still generating", async () => {
  let reads = 0;
  const { store, tick } = recoveryFixture(async () => ++reads <= 152
    ? { messages: [message(1)], is_generating: true }
    : { messages: [message(1), { ...message(2, "completed"), role: "assistant" }], is_generating: false });
  await store.loadHistory(1);
  for (let i = 0; i < 151; i++) await tick();
  assert.equal(store.isLoading, true);
  await tick();
  assert.equal(store.messages.at(-1).content, "completed");
  assert.equal(store.isLoading, false);
  store.$reset();
});

test("a recovery response from the previous session cannot start another poll or overwrite history", async () => {
  const pending = deferred();
  const { store, tick } = recoveryFixture(() => pending.promise);
  store.setActiveSession(1);
  await store.sendChatMessage(1, "question");
  await tick();
  store.setActiveSession(2); store.setHistory([message(20)]);
  pending.resolve({ messages: [], is_generating: false });
  for (let i = 0; i < 12; i++) await Promise.resolve();
  assert.deepEqual(store.messages.map(m => m.id), [20]);
  assert.equal(store.errorMessage, null);
  store.$reset();
});

test("App bridge recovers a disconnected turn through the same history polling", async () => {
  const { store, tick } = recoveryFixture(async () => ({
    messages: [message(1), { ...message(2, "recovered"), role: "assistant" }], is_generating: false,
  }), "APP-PLUS");
  store.setActiveSession(1);
  await store.sendChatMessage(1, "question");
  const request = store.activeStreamRequest;
  const bridgeLoader = createLoader({ mocks: { "@/store/chatStore": { useChatStore: () => store } } });
  const bridge = bridgeLoader("composables/useChatStreamBridge.ts").useChatStreamBridge();
  bridge.onBridgeMessage({ detail: { ...request, type: "error", error: "network disconnected" } });
  assert.equal(store.isLoading, true);
  await tick();
  assert.equal(store.messages.at(-1).content, "recovered");
  assert.equal(store.errorMessage, null);
  assert.equal(store.activeStreamRequest, null);
  store.$reset();
});


test("leaving a session while loading model defaults cannot start its chat POST", async () => {
  const pending = deferred();
  let posts = 0;
  const { store } = chatFixture(async () => ({ messages: [] }), async () => { posts++; }, { requestGeneration: () => pending.promise });
  store.setActiveSession(1);
  const sending = store.sendChatMessage(1, "old request");
  store.setActiveSession(2);
  store.setHistory([message(22)]);
  pending.resolve({ model: "flash", thinking_mode: "disabled" });
  await sending;
  assert.equal(posts, 0);
  assert.deepEqual(store.messages.map(item => item.id), [22]);
  assert.equal(store.isLoading, false);
});

test("model settings failure preserves messages and releases loading for send and regenerate", async () => {
  let posts = 0;
  const { store } = chatFixture(async () => ({ messages: [] }), async () => { posts++; }, { requestGeneration: async () => { throw new Error("模型配置加载失败"); } });
  store.setActiveSession(1);
  store.setHistory([message(1), { ...message(2), role: "assistant", content: "existing reply" }]);
  await store.sendChatMessage(1, "new");
  assert.equal(store.messages.length, 2);
  assert.equal(store.isLoading, false);
  await store.regenerateChatMessage(1);
  assert.equal(store.messages[1].content, "existing reply");
  assert.equal(store.isLoading, false);
  assert.equal(store.errorMessage, "模型配置加载失败");
  assert.equal(posts, 0);
});
