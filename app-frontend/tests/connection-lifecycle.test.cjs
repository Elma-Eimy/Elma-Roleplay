const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { createPinia, setActivePinia } = require("pinia");
const { createLoader, deferred, sourceRoot } = require("./helpers/load-ts.cjs");

function connectionFixture() {
  const storage = new Map([["api_base_url", "https://server-a.invalid"]]);
  let failSave = false;
  const uni = {
    getStorageSync: key => storage.get(key),
    setStorageSync(key, value) { if (failSave) throw new Error("storage unavailable"); storage.set(key, value); },
  };
  const events = createLoader()("utils/connectionEvents.ts");
  // 只替换构建器注入的环境变量，执行实际连接配置模块。
  const source = fs.readFileSync(path.join(sourceRoot, "api/config.ts"), "utf8")
    .replace("import.meta.env.VITE_API_BASE_URL", "undefined");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, uni,
    console: { ...console, error() {} }, require(name) {
      assert.equal(name, "../utils/connectionEvents"); return events;
    } });
  return { config: module.exports, events, uni, failSave() { failSave = true; } };
}

test("only a successfully persisted different server invalidates subscribers", () => {
  const f = connectionFixture(); const seen = [];
  const unsubscribe = f.events.onServerChange(() => seen.push(f.config.getBaseUrl()));
  f.config.setSavedBaseUrl("https://server-a.invalid/");
  assert.deepEqual(seen, []);
  f.config.setSavedBaseUrl("https://server-b.invalid///");
  assert.deepEqual(seen, ["https://server-b.invalid"]);
  f.failSave();
  assert.throws(() => f.config.setSavedBaseUrl("https://server-c.invalid"), /storage unavailable/);
  assert.equal(f.config.getBaseUrl(), "https://server-b.invalid");
  assert.equal(seen.length, 1);
  unsubscribe(); f.events.notifyServerChange(); assert.equal(seen.length, 1);
});

test("server saves reset live stores and reject old history, details and character lists even after A-B-A", async t => {
  setActivePinia(createPinia());
  const f = connectionFixture();
  const history = deferred(), details = deferred(), characters = deferred();
  let characterReads = 0;
  const load = createLoader({ mocks: {
    "@/api/config": f.config, "@/utils/connectionEvents": f.events,
    "@/api/sessions": { getSessionHistory: () => history.promise, getSession: () => details.promise },
    "@/api/characters": { getCharacters: () => characters.promise, getCharacter: async () => { characterReads++; return { id: 9 }; } },
    "@/api/chat": { sendMessageStream: async () => {} },
    "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    "./chatSettingsStore": { useChatSettingsStore: () => ({ activateSession() {}, clearParameters() {}, $reset() {} }) },
  }, globals: { uni: f.uni } });
  const chat = load("store/chatStore.ts").useChatStore();
  const persona = load("store/personaStore.ts").usePersonaStore();
  t.after(() => { chat.$dispose(); persona.$dispose(); });
  persona.activeCharacter = { id: 1 }; persona.currentPersona = { affection_score: 20 };
  const historyAction = chat.loadHistory(1), detailAction = persona.loadSessionDetail(1), listAction = persona.loadCharacters();
  f.config.setSavedBaseUrl("https://server-b.invalid");
  assert.equal(chat.activeSessionId, null); assert.equal(chat.isLoading, false);
  assert.equal(persona.activeCharacter, null); assert.equal(persona.currentPersona, null);
  assert.equal(persona.isLoadingPersona, false); assert.equal(persona.isLoadingCharacters, false);
  f.config.setSavedBaseUrl("https://server-a.invalid");
  persona.characterList = [{ id: 22 }];
  details.resolve({ character: { id: 9 }, persona: { affection_score: 99 } });
  history.resolve({ messages: [{ id: 9 }] }); characters.resolve({ characters: [{ id: 9 }] });
  await Promise.all([historyAction, detailAction, listAction]);
  assert.equal(chat.messages.length, 0); assert.equal(persona.currentPersona, null);
  assert.equal(persona.characterList[0].id, 22); assert.equal(characterReads, 0);
  chat.$dispose(); persona.$dispose();
  chat.setActiveSession(30); persona.activeCharacter = { id: 30 };
  f.events.notifyServerChange();
  assert.equal(chat.activeSessionId, 30); assert.equal(persona.activeCharacter.id, 30);
});
