const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, effectScope } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

const card = () => ({ id: 1, name: "Traveler", description: "English setting {{char}}", personality: "Kind",
  first_mes: "Hello {{user}}", system_prompt_override: "ORIGINAL_PROMPT",
  extensions: { alternate_greetings: ["", "Second"], third_party: { prompt: "untouched" } } });
const translation = () => ({ source_hash: "hash", model: "deepseek-flash", created_at: "2026-10-20",
  fields: { description: "中文背景 {{char}}", personality: "温柔", scenario: "", first_mes: "你好 {{user}}",
    mes_example: "", creator_notes: "", alternate_greetings: ["", "第二个开场"] } });
async function flush() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
function fixture(api) {
  let server = "https://one.example.invalid";
  const scope = effectScope();
  const source = ref(card());
  const load = createLoader({ mocks: { "@/api/characterTranslations": api, "@/api/config": { getBaseUrl: () => server } } });
  const state = scope.run(() => load("composables/useCharacterTranslation.ts").useCharacterTranslation(() => source.value));
  return { scope, source, setServer(value) { server = value; }, ...state };
}

test("cached Chinese is the default reading version while original card and hidden prompts stay unchanged", async () => {
  const state = fixture({ getCharacterTranslation: async () => ({ translation: translation() }) });
  await flush();
  assert.equal(state.language.value, "zh");
  assert.equal(state.readingCard.value.description, "中文背景 {{char}}");
  assert.equal(state.source.value.description, "English setting {{char}}");
  assert.equal(state.readingCard.value.system_prompt_override, "ORIGINAL_PROMPT");
  assert.deepEqual([...state.readingCard.value.extensions.alternate_greetings], ["", "第二个开场"]);
  assert.deepEqual([...state.source.value.extensions.alternate_greetings], ["", "Second"]);
  state.language.value = "original";
  assert.equal(state.readingCard.value.description, state.source.value.description);
  state.scope.stop();
});

test("translation starts only on click and does not block the original reading view", async () => {
  let calls = 0;
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: null }), translateCharacter: () => { calls++; return pending.promise; } });
  await flush();
  assert.equal(calls, 0);
  const request = state.translate();
  assert.equal(state.translating.value, true);
  assert.equal(state.readingCard.value.description, state.source.value.description);
  pending.resolve({ translation: translation() }); await request;
  assert.equal(calls, 1);
  assert.equal(state.language.value, "zh");
  state.scope.stop();
});

test("replacing or editing a card ignores old translation results and invalidates the reading cache", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: null }), translateCharacter: () => pending.promise });
  await flush();
  const request = state.translate();
  state.source.value = { ...card(), id: 2, description: "Another card" };
  pending.resolve({ translation: translation() }); await request; await flush();
  assert.equal(state.translation.value, null);
  assert.equal(state.language.value, "original");
  assert.equal(state.readingCard.value.description, "Another card");
  state.scope.stop();
});

test("a slow cache lookup cannot overwrite a newly generated translation", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: () => pending.promise, translateCharacter: async () => ({ translation: translation() }) });
  await state.translate();
  pending.resolve({ translation: null }); await flush();
  assert.equal(state.language.value, "zh");
  assert.ok(state.translation.value);
  state.scope.stop();
});

test("leaving the view invalidates an unfinished translation", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: null }), translateCharacter: () => pending.promise });
  await flush();
  const request = state.translate();
  state.scope.stop();
  pending.resolve({ translation: translation() }); await request;
  assert.equal(state.translation.value, null);
  assert.equal(state.language.value, "original");
});

test("failed refresh preserves cached Chinese and closing import ignores in-flight results", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: translation() }), translateCharacter: () => pending.promise });
  await flush();
  const request = state.translate(true);
  pending.reject(new Error("translation unavailable")); await request;
  assert.ok(state.error.value);
  assert.equal(state.readingCard.value.description, "中文背景 {{char}}");
  state.source.value = null;
  assert.equal(state.translation.value, null);
  state.scope.stop();
});

test("translation API uses shared authenticated requests, separate cache lookup and reading-only payloads", async () => {
  const calls = [];
  const load = createLoader({ mocks: { "./config": { USE_MOCK: false, request: async (...args) => { calls.push(args); return { translation: null }; } } } });
  const api = load("api/characterTranslations.ts");
  await api.getCharacterTranslation(card()); await api.translateCharacter(card(), true);
  assert.deepEqual(calls.map(call => call[0]), ["/characters/translation-cache", "/characters/translate"]);
  const payload = JSON.parse(calls[1][1].body);
  assert.equal(payload.force, true);
  assert.equal(payload.card.description, card().description);
  assert.equal(payload.card.system_prompt_override, undefined);
  assert.equal(payload.card.extensions.third_party, undefined);
  assert.equal(calls[1][1].timeout, 600000);
});

test("offline Mock never pretends that an online translation was generated", async () => {
  const load = createLoader({ mocks: { "./config": { USE_MOCK: true } } });
  const api = load("api/characterTranslations.ts");
  assert.equal((await api.getCharacterTranslation(card())).translation, null);
  await assert.rejects(api.translateCharacter(card()), /离线/);
});

test("a delayed cache response respects the user's original-language choice", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: () => pending.promise });
  // 即使当前已是原文，再次点击也表示用户明确选择。
  state.selectLanguage("original");
  pending.resolve({ translation: translation() }); await flush();
  assert.ok(state.translation.value);
  assert.equal(state.language.value, "original");
  state.scope.stop();
});

test("an in-flight translation respects a later switch to the original version", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: translation() }), translateCharacter: () => pending.promise });
  await flush();
  const request = state.translate(true);
  state.selectLanguage("original");
  pending.resolve({ translation: translation() }); await request;
  assert.equal(state.language.value, "original");
  state.scope.stop();
});

test("switching servers rejects the previous response and reloads matching cards from the new server", async () => {
  const pending = deferred();
  let reads = 0;
  const state = fixture({ getCharacterTranslation: () => ++reads === 1 ? pending.promise : Promise.resolve({ translation: null }) });
  state.setServer("https://two.example.invalid");
  pending.resolve({ translation: translation() }); await flush();
  assert.equal(state.translation.value, null);
  // 新服务器可能恰好有相同 id、相同原文；仍应重新查询该服务器的缓存。
  state.source.value = { ...card() }; await flush();
  assert.equal(reads, 2);
  assert.equal(state.translation.value, null);
  state.scope.stop();
});

test("a translation from the previous server cannot apply errors or leave the current view busy", async () => {
  const pending = deferred();
  const state = fixture({ getCharacterTranslation: async () => ({ translation: null }), translateCharacter: () => pending.promise });
  await flush();
  const request = state.translate();
  state.setServer("https://two.example.invalid");
  pending.reject(new Error("old server failure")); await request;
  assert.equal(state.translation.value, null);
  assert.equal(state.error.value, "");
  assert.equal(state.translating.value, false);
  state.scope.stop();
});
