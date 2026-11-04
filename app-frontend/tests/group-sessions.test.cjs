const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");

const plain = value => JSON.parse(JSON.stringify(value));
const cards = () => ({ title: " group ", user_nickname: " user ", shared_setting: " ", members: [
  { character_id: 1, origin: { mode: "card" } }, { character_id: 2, origin: { mode: "card" } },
] });
function fixture({ mock = false, request = async () => ({ ok: true }), db } = {}) {
  let writes = 0;
  db ??= { characters: [1, 2, 3].map(id => ({ id, name: `actor${id}`, avatar_path: "" })),
    sessions: [{ id: 10, character_id: 1, persona: { id: 100 }, updated_at: "2026-01-01" }], messages: { 10: [] } };
  const config = { USE_MOCK: mock, request, getMockDB: () => db, setMockDB: next => { db = next; writes++; } };
  const load = createLoader({ mocks: { "./config": config, "../config": config } });
  return { api: load("api/groupSessions.ts"), load, get db() { return db; }, get writes() { return writes; } };
}

test("group API keeps HTTP methods, pagination and creation payload through shared request", async () => {
  const calls = [];
  const f = fixture({ request: async (...args) => { calls.push(args); return { ok: true }; } });
  const params = cards();
  await f.api.createGroupSession(params);
  await f.api.getGroupSessions(5, 10);
  await f.api.getGroupSession(21);
  await f.api.deleteGroupSession(21);
  assert.deepEqual(calls.map(call => call[0]), ["/group-sessions", "/group-sessions?limit=5&offset=10", "/group-sessions/21", "/group-sessions/21/delete"]);
  assert.equal(calls[0][1].method, "POST");
  assert.deepEqual(JSON.parse(calls[0][1].body), params);
  assert.deepEqual(plain(calls[3][1]), { method: "POST" });
});

test("failed group creation never retries POST", async () => {
  let calls = 0;
  const f = fixture({ request: async () => { calls++; throw new Error("timeout"); } });
  await assert.rejects(f.api.createGroupSession(cards()), /timeout/);
  assert.equal(calls, 1);
});

test("card-only Mock creates independent members, persists and never mixes into single stories", async () => {
  const f = fixture({ mock: true });
  const before = plain(f.db.sessions);
  const created = await f.api.createGroupSession(cards());
  assert.equal(created.title, "group");
  assert.equal(created.user_nickname, "user");
  assert.equal(created.shared_setting, null);
  assert.equal(created.can_generate, false);
  assert.deepEqual(plain(created.members.map(member => member.slot)), [1, 2]);
  assert.notEqual(created.members[0].persona_id, created.members[1].persona_id);
  assert.equal(created.members[0].origin.inherited_memory_count, 0);
  assert.deepEqual(plain(f.db.sessions), before);
  assert.deepEqual(plain(f.db.messages), { 10: [] });
  created.members[0].state.current_mood = "edited response";
  const saved = await f.api.getGroupSession(created.session_id);
  assert.equal(saved.members[0].state.current_mood, null);
  const other = f.load("api/groupSessions.ts");
  assert.equal((await other.getGroupSessions()).total, 1);
});

test("Mock group pages remain stable when timestamps tie and deletion preserves single data", async () => {
  const f = fixture({ mock: true });
  const ids = [];
  for (let i = 0; i < 3; i++) ids.push((await f.api.createGroupSession(cards())).session_id);
  f.db.groupSessions.forEach(group => { group.updated_at = "2026-11-04T12:00:00"; });
  const page = await f.api.getGroupSessions(2, 0);
  assert.deepEqual(plain(page.sessions.map(group => group.session_id)), ids.slice().reverse().slice(0, 2));
  assert.equal(page.total, 3);
  assert.equal(page.has_more, true);
  assert.deepEqual(plain((await f.api.getGroupSessions(2, 2)).sessions.map(group => group.session_id)), [ids[0]]);
  assert.equal((await f.api.deleteGroupSession(ids[0])).members_deleted, 2);
  await assert.rejects(f.api.getGroupSession(ids[0]), /不存在/);
  assert.equal(f.db.sessions.length, 1);
  await assert.rejects(f.api.getGroupSession(10), /仅支持群聊/);
  await assert.rejects(f.api.deleteGroupSession(10), /仅支持群聊/);
  await assert.rejects(f.api.getGroupSessions(101), /分页参数/);
});

test("unsupported snapshot and invalid Mock creation never persist partial results", async () => {
  const f = fixture({ mock: true });
  const imported = cards();
  imported.members[0].origin = { mode: "single_snapshot", session_id: 10 };
  await assert.rejects(f.api.createGroupSession(imported), /暂不支持.*快照/);
  const missing = cards();
  missing.members[1].character_id = 999;
  await assert.rejects(f.api.createGroupSession(missing), /角色不存在/);
  const duplicate = cards();
  duplicate.members[1].character_id = 1;
  await assert.rejects(f.api.createGroupSession(duplicate), /重复/);
  const tooFew = cards();
  tooFew.members.pop();
  await assert.rejects(f.api.createGroupSession(tooFew), /2–3/);
  assert.equal(f.writes, 0);
});

test("Mock prevents deleting a group member's character until the group is removed", async () => {
  const f = fixture({ mock: true });
  const group = await f.api.createGroupSession(cards());
  const characters = f.load("api/characters.ts");
  await assert.rejects(characters.deleteCharacter(1), /群聊使用/);
  assert.equal(f.db.characters.length, 3);
  await f.api.deleteGroupSession(group.session_id);
  await characters.deleteCharacter(1);
  assert.equal(f.db.characters.length, 2);
});

test("single and group Mock creation share the ID space without allowing group branches", async () => {
  const f = fixture({ mock: true });
  const group = await f.api.createGroupSession(cards());
  const singles = f.load("api/sessions.ts");
  const created = await singles.createSession({ character_id: 1, title: "single" });
  assert.notEqual(created.session_id, group.session_id);
  assert.ok(group.members.every(member => member.persona_id !== created.persona_id));
  assert.equal((await f.api.getGroupSession(group.session_id)).kind, "group");
  await assert.rejects(singles.createSession({ character_id: 1, title: "bad", parent_session_id: group.session_id }), /仅支持单聊/);
});
