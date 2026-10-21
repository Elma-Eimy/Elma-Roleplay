const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");

function fixture({ mock = false, db = {}, request = async () => ({ ok: true }) } = {}) {
  let writes = 0;
  const config = { USE_MOCK: mock, request,
    getMockDB: () => db, setMockDB: value => { db = value; writes++; } };
  let clock = 1_700_000_000_000;
  class MockDate extends Date { static now() { return ++clock; } }
  const load = createLoader({ mocks: { "./config": config, "../config": config }, globals: { Date: MockDate } });
  return { api: load("api/sessions.ts"), load, get db() { return db; }, get writes() { return writes; } };
}
const plain = value => JSON.parse(JSON.stringify(value));
const persona = () => ({ id: 10, character_id: 7, affection_score: 20, current_mood: "Calm", cognition_state: "known", current_scenario_override: null });
function seed() {
  return {
    characters: [{ id: 7, name: "角色", avatar_path: "", first_mes: "你好", extensions: { alternate_greetings: ["欢迎"] } }],
    sessions: [1, 2, 3].map(id => ({ id, character_id: 7, title: `story-${id}`,
      parent_session_id: id === 1 ? null : id - 1,
      created_at: "2026-10-20", updated_at: `2026-10-2${id}`,
      persona: persona(), character: { id: 7, name: "角色", avatar_path: "" } })),
    messages: { 1: [
      { id: 11, role: "user", content: "question" },
      { id: 12, role: "assistant", content: "old", parent_id: 11, is_active: true },
      { id: 13, role: "assistant", content: "alternate", parent_id: 11, is_active: false },
    ], 2: [{ id: 21, role: "user", content: "branch" }] },
    memories: {
      1: [{ id: 101, content: "旧事实", created_at: "2026-10-20", importance_score: 0.5 }],
      2: [{ id: 102, content: "新事实", supersedes_id: 101, created_at: "2026-10-21", importance_score: 0.8 }],
    },
  };
}

test("domain APIs preserve HTTP methods, routes, query encoding and request bodies", async () => {
  const calls = [];
  const { api, load } = fixture({ request: async (url, options = {}) => {
    calls.push([url, options.method || "GET", options.body ? JSON.parse(options.body) : null]);
    return { accepted: true };
  } });
  const cases = [
    ["createSession", [{ character_id: 7, title: "新故事" }], "/sessions/create", "POST", { character_id: 7, title: "新故事" }],
    ["getSessions", [7], "/sessions?character_id=7&include_last_message=true&limit=50&offset=0", "GET", null],
    ["getRecentSessions", [4, 2], "/sessions/recent?limit=4&offset=2", "GET", null],
    ["getSession", [2], "/sessions/2", "GET", null],
    ["getSessionHistory", [2], "/sessions/2/history?limit=50", "GET", null],
    ["getSessionHistory", [2, 10, 21], "/sessions/2/history?limit=10&before_id=21", "GET", null],
    ["updateSessionTitle", [2, "new"], "/sessions/2/title", "PUT", { title: "new" }],
    ["deleteSession", [2], "/sessions/2/delete", "POST", null],
    ["triggerSummary", [2], "/sessions/2/trigger_summary", "POST", null],
    ["triggerCognition", [2], "/sessions/2/trigger_cognition", "POST", null],
    ["updateMessage", [21, "edited"], "/sessions/messages/21", "PUT", { content: "edited" }],
    ["deleteMessage", [21], "/sessions/messages/21/delete", "POST", null],
    ["switchCandidate", [13], "/chat/switch_candidate", "POST", { message_id: 13 }],
    ["getSessionMemories", [2], "/sessions/2/memories?scope=all&status=active&limit=20&offset=0", "GET", null],
    ["getSessionMemories", [2, { q: " 中文 & ? ", scope: "inherited", status: "all", limit: 3, offset: 1 }],
      `/sessions/2/memories?scope=inherited&status=all&limit=3&offset=1&q=${encodeURIComponent("中文 & ?")}`, "GET", null],
    ["getCharacterMemoryOverview", [7, 4, 2], "/characters/7/memory-overview?limit=4&offset=2", "GET", null],
    ["createSessionMemory", [2, "事实"], "/sessions/2/memories", "POST", { content: "事实", importance_score: 0.8, memory_type: "fact" }],
    ["updateSessionMemory", [2, 102, "edited", 0.9], "/sessions/2/memories/102", "PUT", { content: "edited", importance_score: 0.9 }],
    ["deleteSessionMemory", [2, 102], "/sessions/2/memories/102", "DELETE", null],
    ["getCompiledPrompt", [2], "/sessions/2/compile_prompt", "GET", null],
  ];
  for (const [name, args, ...expected] of cases) {
    assert.deepEqual(plain(await api[name](...args)), { accepted: true }, name);
    assert.deepEqual(calls.at(-1), expected, name);
  }
  for (const domain of ["messages", "memories", "prompts"]) {
    for (const [name, fn] of Object.entries(load(`api/${domain}.ts`))) assert.equal(api[name], fn, name);
  }
});

test("all-session aggregation advances through pages and preserves the last-message option", async () => {
  const calls = [];
  const { api } = fixture({ request: async url => {
    calls.push(url);
    const second = url.endsWith("offset=2");
    return { sessions: second ? [{ id: 3 }] : [{ id: 1 }, { id: 2 }],
      total: 3, offset: second ? 2 : 0, has_more: !second };
  } });
  const result = await api.getAllSessions(7, false);
  assert.deepEqual(plain(result.sessions), [{ id: 1 }, { id: 2 }, { id: 3 }]);
  assert.equal(result.limit, 3); assert.equal(result.has_more, false);
  assert.deepEqual(calls, [0, 2].map(offset => `/sessions?character_id=7&include_last_message=false&limit=100&offset=${offset}`));
});

test("a transport rejection propagates unchanged and never falls back to Mock data", async () => {
  const failure = new Error("offline");
  const { api } = fixture({ request: async () => { throw failure; } });
  await assert.rejects(api.getSession(1), error => error === failure);
  await assert.rejects(api.getSessionMemories(1), error => error === failure);
});

test("Mock session creation preserves alternate greetings and branch inheritance", async () => {
  const f = fixture({ mock: true, db: seed() });
  const fresh = await f.api.createSession({ character_id: 7, title: "fresh", greeting_index: 0 });
  assert.equal(f.db.messages[fresh.session_id][0].content, "欢迎");
  const branch = await f.api.createSession({ character_id: 7, title: "branch", parent_session_id: 1, start_message_id: 12 });
  const detail = await f.api.getSession(branch.session_id);
  assert.equal(detail.persona.affection_score, 20);
  assert.equal(branch.inherited, true);
  assert.equal(f.db.messages[branch.session_id][0].content, "old");
});

test("Mock session deletion relinks children and removes its messages", async () => {
  const f = fixture({ mock: true, db: seed() });
  await f.api.updateSessionTitle(2, "renamed");
  assert.equal((await f.api.getSession(2)).title, "renamed");
  const deleted = await f.api.deleteSession(2);
  assert.equal(deleted.relinked_children, 1);
  assert.equal((await f.api.getSession(3)).parent_session_id, 1);
  assert.equal(f.db.messages[2], undefined);
  await assert.rejects(f.api.getSession(2), /not found/);
});

test("Mock message edits, history pagination and candidate changes share the same database", async () => {
  const f = fixture({ mock: true, db: seed() });
  await f.api.updateMessage(12, "edited");
  assert.equal((await f.api.getSessionHistory(1, 1, 13)).messages[0].content, "edited");
  await f.api.switchCandidate(13);
  assert.equal(f.db.messages[1][1].is_active, false);
  assert.equal(f.db.messages[1][2].is_active, true);
  assert.equal((await f.api.getSessions(7)).sessions.find(s => s.id === 1).last_message.content, "alternate");
  await f.api.deleteMessage(13);
  await assert.rejects(f.api.updateMessage(99, "missing"), /not found/);
  assert.ok(f.writes >= 3);
});

test("Mock memory inheritance, supersession, filters and overview remain consistent", async () => {
  const { api } = fixture({ mock: true, db: seed() });
  const active = await api.getSessionMemories(3);
  assert.deepEqual(plain(active.items.map(m => m.id)), [102]);
  assert.equal(active.facets.inherited_active, 1);
  assert.equal(active.facets.superseded, 1);
  const old = await api.getSessionMemories(3, { scope: "inherited", status: "superseded", q: "旧" });
  assert.deepEqual(plain(old.items.map(m => m.id)), [101]);
  const overview = await api.getCharacterMemoryOverview(7, 2, 0);
  assert.equal(overview.story_count, 3); assert.equal(overview.has_more, true);
  assert.equal(overview.sessions[0].session_id, 3);
  assert.equal(overview.sessions[0].memory_stats.effective_total, 1);
});

test("Mock memory mutations persist and prompt previews retain token estimates", async () => {
  const f = fixture({ mock: true, db: seed() });
  const created = await f.api.createSessionMemory(3, "new fact");
  await f.api.updateSessionMemory(3, created.memory.id, "changed fact", 0.9);
  assert.equal(f.db.memories[3][0].content, "changed fact");
  await f.api.deleteSessionMemory(3, created.memory.id);
  assert.equal(f.db.memories[3].length, 0);
  const prompt = await f.api.getCompiledPrompt(3);
  assert.equal(prompt.messages.length, 3);
  assert.equal(prompt.token_estimate.is_exact, false);
  assert.ok(prompt.token_estimate.sections.character.estimated_tokens > 0);
});
