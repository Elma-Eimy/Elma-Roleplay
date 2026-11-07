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

test("group operation APIs keep request IDs and query URLs without retrying POST", async () => {
  const calls = [];
  const f = fixture({ request: async (...args) => { calls.push(args); return {}; } });
  const params = { client_request_id: "same-id", expected_group_revision: 2, observed_round_id: 3,
    observed_candidate_id: 4, observed_candidate_revision: 5 };
  await f.api.sendGroupRound(21, { ...params, user_content: "  raw  " });
  await f.api.regenerateGroupRound(21, 3, params);
  await f.api.resumeGroupRound(21, 3, { ...params, target_candidate_id: 6, target_candidate_revision: 1 });
  await f.api.selectGroupCandidate(21, 3, { ...params, target_candidate_id: 4, target_candidate_revision: 5 });
  await f.api.discardGroupRound(21, 3, params);
  await f.api.getGroupRequest(21, "id /?#");
  await f.api.getGroupCandidates(21, 3, 5, 10);
  await f.api.getGroupCandidate(21, 3, 6);
  await f.api.getGroupPortraits(21);
  await f.api.setGroupPortrait(21, 7, { portrait_id: null, expected_group_revision: 2 });
  assert.deepEqual(calls.map(call => call[0]), ["/group-sessions/21/rounds", "/group-sessions/21/rounds/3/regenerate",
    "/group-sessions/21/rounds/3/resume", "/group-sessions/21/rounds/3/select-candidate", "/group-sessions/21/rounds/3/discard",
    "/group-sessions/21/requests/id%20%2F%3F%23", "/group-sessions/21/rounds/3/candidates?limit=5&offset=10", "/group-sessions/21/rounds/3/candidates/6",
    "/group-sessions/21/portraits", "/group-sessions/21/members/7/portrait"]);
  assert.equal(calls.at(-1)[1].method, 'PUT');
  assert.equal(JSON.parse(calls.at(-1)[1].body).portrait_id, null);
  for (const call of calls.slice(0, 5)) {
    assert.equal(call[1].method, "POST");
    assert.equal(JSON.parse(call[1].body).client_request_id, params.client_request_id);
  }
  assert.equal(JSON.parse(calls[0][1].body).user_content, "  raw  ");
  let attempts = 0;
  const broken = fixture({ request: async () => { attempts++; throw new Error("timeout"); } });
  await assert.rejects(broken.api.sendGroupRound(21, { ...params, user_content: "raw" }), /timeout/);
  assert.equal(attempts, 1);
});

test("Mock rejects new generation and recovery capabilities without writes or fake receipts", async () => {
  const f = fixture({ mock: true });
  const group = await f.api.createGroupSession(cards());
  const params = { client_request_id: "same-id", expected_group_revision: 0 };
  const snapshot = plain(f.db), writes = f.writes;
  for (const action of [() => f.api.sendGroupRound(group.session_id, { ...params, user_content: "hello" }),
    () => f.api.regenerateGroupRound(group.session_id, 1, params), () => f.api.resumeGroupRound(group.session_id, 1, params),
    () => f.api.selectGroupCandidate(group.session_id, 1, params), () => f.api.discardGroupRound(group.session_id, 1, params),
    () => f.api.getGroupRequest(group.session_id, "same-id"), () => f.api.getGroupCandidates(group.session_id, 1),
    () => f.api.getGroupCandidate(group.session_id, 1, 1), () => f.api.getGroupPortraits(group.session_id),
    () => f.api.setGroupPortrait(group.session_id, 1, { portrait_id: null, expected_group_revision: 0 })]) {
    await assert.rejects(action(), /离线模式暂不支持/);
  }
  assert.equal(f.writes, writes);
  assert.deepEqual(plain(f.db), snapshot);
  await assert.rejects(f.api.getGroupRequest(10, "id"), /仅支持群聊/);
});

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

test("group round API uses shared GET and the explicit session pagination", async () => {
  const calls = [];
  const f = fixture({ request: async (...args) => { calls.push(args); return { rounds: [] }; } });
  await f.api.getGroupRounds(21, 5, 10);
  assert.deepEqual(calls, [["/group-sessions/21/rounds?limit=5&offset=10"]]);
});

test("mock round history is readonly, paginated and removed with its group", async () => {
  const f = fixture({ mock: true });
  const group = await f.api.createGroupSession(cards());
  f.db.groupRounds = { [group.session_id]: [1, 2].map(id => ({ round_id: id, round_index: id,
    candidate_id: id, status: "failed", confirmed: false, user_content: "虚构样本", created_at: "2026-11-05", utterances: [] })) };
  const writes = f.writes;
  const page = await f.api.getGroupRounds(group.session_id, 1, 0);
  assert.equal(page.rounds[0].round_id, 2); assert.equal(page.has_more, true);
  page.rounds[0].user_content = "mutated";
  assert.equal(f.db.groupRounds[group.session_id][1].user_content, "虚构样本");
  assert.equal(f.writes, writes);
  await assert.rejects(f.api.getGroupRounds(10), /仅支持群聊/);
  await assert.rejects(f.api.getGroupRounds(group.session_id, 101), /分页/);
  await f.api.deleteGroupSession(group.session_id);
  assert.equal(f.db.groupRounds[group.session_id], undefined);
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
