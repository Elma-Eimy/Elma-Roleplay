const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

function fixture(getSettings = async () => ({})) {
  setActivePinia(createPinia());
  const storage = new Map();
  let server = "https://one.test";
  const load = createLoader({
    mocks: {
      "@/api/config": { getBaseUrl: () => server },
      "@/api/settings": {
        getSettings,
        DEFAULT_SETTINGS: {
          default_chat_model: "deepseek-flash",
          model_profiles: [],
          model_catalog: [
            {
              id: "deepseek-flash",
              label: "Flash",
              adapter: "deepseek",
              thinking: "toggle",
              efforts: ["low", "high", "max"],
            },
          ],
          reasoning_mode: false,
          reasoning_effort: "high",
        },
      },
    },
    globals: {
      uni: {
        getStorageSync: (key) => storage.get(key),
        setStorageSync: (key, value) => storage.set(key, value),
      },
    },
  });
  return {
    store: load("store/chatSettingsStore.ts").useChatSettingsStore(),
    storage,
    load,
    setServer: (value) => {
      server = value;
    },
  };
}

test("story choices are concrete and persist independently without legacy switching", async () => {
  const { store } = fixture();
  store.activateSession(1);
  assert.equal((await store.requestGeneration(1)).thinking_mode, "disabled");
  assert.equal((await store.requestGeneration(1)).use_reasoning, undefined);
  store.modelId = "deepseek-flash";
  store.thinkingMode = "enabled";
  store.reasoningEffort = "max";
  store.activateSession(2);
  await store.refreshModels();
  assert.equal(store.modelId, "deepseek-flash");
  assert.equal(store.thinkingMode, "disabled");
  store.modelId = "deepseek-v4-pro";
  store.thinkingMode = "disabled";
  store.activateSession(1);
  assert.equal(store.modelId, "deepseek-flash");
  assert.equal(store.reasoningEffort, "max");
  assert.equal((await store.requestGeneration(1)).thinking_mode, "enabled");
  assert.equal((await store.requestGeneration(2)).model, "deepseek-v4-pro");
  store.resetGeneration();
  assert.equal((await store.requestGeneration(1)).model, "deepseek-flash");
});

test("same story ids on different servers do not share model settings and deletion clears preferences", () => {
  const { store, setServer } = fixture();
  store.activateSession(8);
  store.modelId = "first-model";
  setServer("https://two.test");
  store.activateSession(8);
  assert.equal(store.modelId, "");
  store.modelId = "second-model";
  store.inheritSession(8, 9);
  store.activateSession(9);
  assert.equal(store.modelId, "second-model");
  setServer("https://one.test");
  store.activateSession(8);
  assert.equal(store.modelId, "first-model");
  store.removeSession(8);
  store.activateSession(8);
  assert.equal(store.modelId, "");
});

test("a branch copies preferences once and then evolves independently", () => {
  const { store } = fixture();
  store.activateSession(1);
  store.modelId = "deepseek-flash";
  store.thinkingMode = "enabled";
  store.reasoningEffort = "max";
  store.inheritSession(1, 2);
  store.activateSession(2);
  assert.equal(store.reasoningEffort, "max");
  store.thinkingMode = "disabled";
  store.activateSession(1);
  assert.equal(store.thinkingMode, "enabled");
});

test("late global settings from the previous server cannot replace current defaults", async () => {
  const pending = deferred();
  const { store, setServer } = fixture(() => pending.promise);
  const request = store.refreshModels();
  setServer("https://two.test");
  pending.resolve({ default_chat_model: "old-server-model" });
  await request;
  assert.equal(store.defaults.default_chat_model, "deepseek-flash");
});

for (const platform of ["H5", "MP-WEIXIN", "APP-PLUS"]) {
test(`${platform} sends and regenerations share settings while preserving their message boundaries`, async () => {
  const { store: settings } = fixture();
  const requests = [];
  const load = createLoader({
    platform,
    mocks: {
      "@/api/config": { getBaseUrl: () => "https://one.test", getSavedApiKey: () => "" },
      "@/api/sessions": {},
      "@/api/chat": {
        sendMessageStream: async (request, chunk, done) => {
          requests.push(request);
          done({
            assistant_message_id: 9,
            user_message_id: 8,
            affection_score: 0,
            model_used: request.model,
          });
        },
      },
      "./chatSettingsStore": { useChatSettingsStore: () => settings },
      "./personaStore": {
        usePersonaStore: () => ({
          userNickname: "玩家",
          applyAffectionChange() {},
        }),
      },
      "@/composables/useAudioPlayer": {
        useAudioPlayer: () => ({ stopMessageTTS() {} }),
      },
    },
  });
  const chat = load("store/chatStore.ts").useChatStore();
  chat.setActiveSession(4);
  settings.modelId = "deepseek-flash";
  settings.thinkingMode = "enabled";
  settings.reasoningEffort = "max";
  settings.temperature = 0;
  settings.top_p = null;
  settings.presence_penalty = 0;
  settings.frequency_penalty = 0.25;
  settings.repetition_penalty = 1.1;
  function finishAppRequest(isRegenerate) {
    if (platform !== "APP-PLUS") return;
    const request = chat.activeStreamRequest;
    assert.ok(request);
    assert.equal(Boolean(request.userMessageTempId), !isRegenerate);
    requests.push(request.params);
    chat.completeStream(request.placeholderId, {
      assistant_message_id: 9,
      user_message_id: 8,
      affection_score: 0,
      model_used: request.params.model,
    }, request.userMessageTempId);
  }
  await chat.sendChatMessage(4, "Hello");
  finishAppRequest(false);
  await chat.regenerateChatMessage(4);
  finishAppRequest(true);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.session_id, 4);
    assert.equal(request.user_message, "Hello");
    assert.equal(request.user_nickname, "玩家");
    assert.equal(request.model, "deepseek-flash");
    assert.equal(request.thinking_mode, "enabled");
    assert.equal(request.reasoning_effort, "max");
    assert.equal(request.use_reasoning, undefined);
    assert.equal(request.temperature, 0);
    assert.equal(request.top_p, undefined);
    assert.equal(request.presence_penalty, 0);
    assert.equal(request.frequency_penalty, 0.25);
    assert.equal(request.repetition_penalty, 1.1);
    assert.equal(Object.hasOwn(JSON.parse(JSON.stringify(request)), "top_p"), false);
  }
  assert.equal(Object.hasOwn(requests[0], "is_regenerate"), false);
  assert.equal(requests[1].is_regenerate, true);
  assert.equal(chat.messages.filter(message => message.role === "user").length, 1);
  assert.equal(chat.messages.filter(message => message.role === "assistant").length, 1);

  settings.temperature = 0.8;
  settings.top_p = 0.6;
  await chat.sendChatMessage(4, "Next");
  finishAppRequest(false);
  assert.equal(requests.length, 3);
  assert.equal(requests[2].temperature, 0.8);
  assert.equal(requests[2].top_p, 0.6);
  assert.equal(requests[0].temperature, 0);
  assert.equal(requests[1].top_p, undefined);
  chat.$reset();
});
}


test("default updates affect new stories while existing stories keep their snapshot", async () => {
  let defaults = { default_chat_model: "deepseek-flash", reasoning_mode: true, reasoning_effort: "max" };
  const { store } = fixture(async () => defaults);
  store.activateSession(1);
  await store.refreshModels();
  assert.equal(store.thinkingMode, "enabled");
  assert.equal(store.reasoningEffort, "max");
  defaults = { default_chat_model: "deepseek-v4-pro", reasoning_mode: false, reasoning_effort: "low" };
  await store.refreshModels();
  assert.equal(store.modelId, "deepseek-flash");
  assert.equal(store.reasoningEffort, "max");
  store.activateSession(2);
  await store.refreshModels();
  assert.equal(store.modelId, "deepseek-v4-pro");
  assert.equal(store.reasoningEffort, "low");
  store.activateSession(1);
  assert.equal(store.thinkingMode, "enabled");
});

test("legacy inheritance is migrated once, preserves explicit choices and resolves missing effort", async () => {
  const { store, storage } = fixture(async () => ({ reasoning_mode: true, reasoning_effort: null }));
  storage.set("story_generation_v1:https://one.test", JSON.stringify({ 1: { model: "", thinking_mode: "inherit", reasoning_effort: "inherit" },
    2: { model: "deepseek-flash", thinking_mode: "disabled", reasoning_effort: "max" } }));
  store.activateSession(1);
  await store.refreshModels();
  assert.equal(store.modelId, "deepseek-flash");
  assert.equal(store.thinkingMode, "enabled");
  assert.equal(store.reasoningEffort, "high");
  store.activateSession(2);
  assert.equal(store.thinkingMode, "disabled");
  assert.equal(store.reasoningEffort, "max");
  const persisted = JSON.parse(storage.get("story_generation_v1:https://one.test"));
  assert.equal(persisted[1].reasoning_effort, "high");
});

test("first send waits for server defaults and concurrent loads share one request", async () => {
  const pending = deferred();
  let calls = 0;
  const { store } = fixture(() => { calls++; return pending.promise; });
  store.activateSession(1);
  const refresh = store.refreshModels();
  const request = store.requestGeneration(1);
  assert.equal(calls, 1);
  pending.resolve({ reasoning_mode: true, reasoning_effort: "max" });
  await refresh;
  assert.equal((await request).reasoning_effort, "max");
});

test("failed initial settings load blocks generation instead of using guessed defaults", async () => {
  const { store } = fixture(async () => { throw new Error("offline"); });
  store.activateSession(1);
  await assert.rejects(store.requestGeneration(1), /模型配置尚未加载/);
});

test("a new story cannot snapshot stale cached defaults when refreshing fails", async () => {
  let fail = false;
  const { store } = fixture(async () => {
    if (fail) throw new Error("offline");
    return {};
  });
  store.activateSession(1);
  await store.refreshModels();
  fail = true;
  store.activateSession(2);
  await assert.rejects(store.requestGeneration(2), /模型配置尚未加载/);
  store.activateSession(1);
  assert.equal((await store.requestGeneration(1)).model, "deepseek-flash");
});

test("same-label model ids remain distinguishable and strength follows supported capabilities", () => {
  const { load } = fixture();
  const { modelOptionLabel, snapshotGeneration } = load("utils/generation.ts");
  const models = ["deepseek-flash", "deepseek-v4-flash"].map(id => ({ id, label: "DeepSeek Flash", adapter: "deepseek", thinking: "toggle", efforts: ["low", "high", "max"] }));
  assert.equal(modelOptionLabel(models[0], models), "DeepSeek Flash (deepseek-flash)");
  const settings = { default_chat_model: models[0].id, reasoning_mode: true, reasoning_effort: "medium", model_catalog: models, model_profiles: [] };
  assert.equal(snapshotGeneration(settings, {}).reasoning_effort, "high");
  settings.model_catalog = [{ id: "fixed", label: "Fixed", adapter: "reasoning", thinking: "always", efforts: ["low", "medium", "high"] }];
  assert.equal(snapshotGeneration(settings, { model: "fixed", thinking_mode: "disabled", reasoning_effort: "max" }).thinking_mode, "enabled");
  assert.equal(snapshotGeneration(settings, { model: "fixed", reasoning_effort: "max" }).reasoning_effort, "high");
});
