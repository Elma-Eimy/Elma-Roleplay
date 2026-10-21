const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, effectScope, nextTick } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");
const plain = value => JSON.parse(JSON.stringify(value));
const snapshot = (scene = "客厅", revision = "r1") => ({ session_id: 1, revision, state: { scene, characters: { 露娜: { posture: "坐着", clothing: "白衬衫" } } } });
const flush = async () => { for (let i = 0; i < 5; i++) await nextTick(); };

function fixture(api = {}) {
  const id = ref(1), generating = ref(false);
  let server = "https://one.test";
  const load = createLoader({ mocks: {
    "@/api/config": { getBaseUrl: () => server },
    "@/api/roleStates": { getRoleState: async () => snapshot(), updateRoleState: async () => snapshot("窗边", "r2"), ...api },
  } });
  const scope = effectScope();
  const state = scope.run(() => load("composables/useRoleState.ts").useRoleState(() => id.value, () => generating.value));
  return { ...state, scope, id, generating, setServer: value => { server = value; } };
}

test("manual save sends only changed fields including explicit clearing", async () => {
  let request;
  const state = fixture({ updateRoleState: async (...args) => { request = args; return snapshot("客厅", "r2"); } });
  await flush();
  state.beginEdit();
  state.actors.value[0].posture = "站着";
  state.actors.value[0].clothing = "";
  await state.save();
  assert.deepEqual(plain(request), [1, "r1", { characters: { 露娜: { posture: "站着", clothing: null } } }]);
  assert.equal(state.editing.value, false);
  state.scope.stop();
});

test("a late load from an old story cannot replace current state", async () => {
  const pending = deferred();
  const state = fixture({ getRoleState: id => id === 1 ? pending.promise : Promise.resolve({ ...snapshot("新故事"), session_id: 2 }) });
  state.id.value = 2;
  await flush();
  pending.resolve(snapshot("旧故事"));
  await flush();
  assert.equal(state.snapshot.value.state.scene, "新故事");
  state.scope.stop();
});

test("conflict keeps drafts and cancel refreshes the current authoritative state", async () => {
  let current = snapshot();
  const state = fixture({ getRoleState: async () => current, updateRoleState: async () => { throw new Error('409 {"detail":"剧情或状态已变化"}'); } });
  await flush();
  state.beginEdit();
  state.scene.value = "手动草稿";
  await state.load();
  assert.equal(state.scene.value, "手动草稿");
  await state.save();
  assert.equal(state.editing.value, true);
  assert.equal(state.scene.value, "手动草稿");
  assert.match(state.error.value, /剧情或状态已变化/);
  current = snapshot("新剧情", "r2");
  await state.cancel();
  assert.equal(state.snapshot.value.state.scene, "新剧情");
  state.scope.stop();
});

test("late save after leaving the story or changing servers cannot mutate new state", async () => {
  const pending = deferred();
  const state = fixture({ updateRoleState: () => pending.promise });
  await flush();
  state.beginEdit();
  state.scene.value = "旧服务器草稿";
  const saving = state.save();
  state.setServer("https://two.test");
  state.id.value = 2;
  await flush();
  pending.resolve(snapshot("旧保存结果", "old"));
  await saving;
  assert.equal(state.snapshot.value.state.scene, "客厅");
  assert.equal(state.busy.value, false);
  state.scope.stop();
});

test("generation blocks editing and saving while removing an actor clears only its known fields", async () => {
  let request;
  const state = fixture({ updateRoleState: async (...args) => { request = args; return snapshot(); } });
  await flush();
  state.generating.value = true;
  state.beginEdit();
  assert.equal(state.editing.value, false);
  state.generating.value = false;
  state.beginEdit();
  state.actors.value = [];
  state.generating.value = true;
  await state.save();
  assert.equal(request, undefined);
  state.generating.value = false;
  await state.save();
  assert.deepEqual(plain(request[2]), { characters: { 露娜: { posture: null, clothing: null } } });
  state.scope.stop();
});

test("API uses authenticated request boundary and offline Mock explicitly rejects unsupported writes", async () => {
  const calls = [];
  const api = createLoader({ mocks: { "./config": { USE_MOCK: false, request: async (...args) => { calls.push(args); return snapshot(); } } } })("api/roleStates.ts");
  await api.getRoleState(3);
  await api.updateRoleState(3, "revision", { scene: "窗边" });
  assert.equal(calls[0][0], "/sessions/3/role-state");
  assert.equal(calls[1][1].method, "PUT");
  assert.deepEqual(JSON.parse(calls[1][1].body), { expected_revision: "revision", patch: { scene: "窗边" } });
  const offline = createLoader({ mocks: { "./config": { USE_MOCK: true } } })("api/roleStates.ts");
  await assert.rejects(offline.updateRoleState(3, "r1", {}), /离线模式/);
});
