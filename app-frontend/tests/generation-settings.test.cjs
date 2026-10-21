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

test("story overrides persist independently and inherit does not send the legacy model-switching flag", () => {
  const { store } = fixture();
  store.activateSession(1);
  assert.equal(store.requestGeneration(1).thinking_mode, "inherit");
  assert.equal(store.requestGeneration(1).use_reasoning, undefined);
  store.modelId = "deepseek-flash";
  store.thinkingMode = "enabled";
  store.reasoningEffort = "max";
  store.activateSession(2);
  assert.equal(store.modelId, "");
  assert.equal(store.thinkingMode, "inherit");
  store.modelId = "deepseek-v4-pro";
  store.thinkingMode = "disabled";
  store.activateSession(1);
  assert.equal(store.modelId, "deepseek-flash");
  assert.equal(store.reasoningEffort, "max");
  assert.equal(store.requestGeneration(1).thinking_mode, "enabled");
  assert.equal(store.requestGeneration(2).model, "deepseek-v4-pro");
  store.resetGeneration();
  assert.equal(store.requestGeneration(1).model, undefined);
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

test("new sends and regenerations carry identical independent model and thinking choices", async () => {
  const { store: settings } = fixture();
  const requests = [];
  const load = createLoader({
    mocks: {
      "@/api/config": {},
      "@/api/sessions": {},
      "@/api/chat": {
        sendMessageStream: async (request, chunk, done) => {
          requests.push(request);
          done({
            assistant_message_id: 9,
            affection_score: 0,
            model_used: request.model,
          });
        },
      },
      "./chatSettingsStore": { useChatSettingsStore: () => settings },
      "./personaStore": {
        usePersonaStore: () => ({
          userNickname: "用户",
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
  await chat.sendChatMessage(4, "Hello");
  await chat.regenerateChatMessage(4);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.model, "deepseek-flash");
    assert.equal(request.thinking_mode, "enabled");
    assert.equal(request.reasoning_effort, "max");
    assert.equal(request.use_reasoning, undefined);
  }
});
