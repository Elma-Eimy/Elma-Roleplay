const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, effectScope } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

const batch = (id = 1, status = "preview") => ({ id, status, groups: [{ id: 0, kind: "event", source_ids: [1, 2], content: "合并的经历", reason: "同一次事件" }],
  sources: [], selected_group_ids: [], results: [], scanned_count: 2, remaining_count: 2, has_more: false, next_after_id: 2 });
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function fixture(extra = {}) {
  const scope = effectScope();
  const session = ref(1);
  let changed = 0;
  let server = "http://one.invalid";
  const api = { getMemoryConsolidations: async () => ({ items: [] }), previewMemoryConsolidation: async () => batch(),
    applyMemoryConsolidation: async () => batch(1, "applied"), undoMemoryConsolidation: async () => batch(1, "undone"), ...extra };
  const load = createLoader({ mocks: { "@/api/config": { getBaseUrl: () => server }, "@/api/memories": api } });
  const state = scope.run(() => load("composables/useMemoryConsolidation.ts").useMemoryConsolidation(() => session.value, () => changed++));
  return { ...state, session, scope, changed: () => changed, setServer(value) { server = value; } };
}

test("preview starts only on click, suggestions require explicit selection and apply refreshes memories", async () => {
  let previews = 0;
  const state = fixture({ previewMemoryConsolidation: async () => { previews++; return batch(); } });
  await flush();
  assert.equal(previews, 0);
  await state.preview();
  assert.equal(state.selected.value.length, 0);
  await state.apply();
  assert.equal(state.changed(), 0);
  state.toggle(0);
  await state.apply();
  assert.equal(state.current.value.status, "applied");
  assert.equal(state.changed(), 1);
  await state.undo(state.current.value);
  assert.equal(state.current.value.status, "undone");
  assert.equal(state.changed(), 2);
  state.scope.stop();
});

test("changing sessions discards an old preview and loads the new story history", async () => {
  const pending = deferred();
  const state = fixture({ previewMemoryConsolidation: () => pending.promise });
  await flush();
  const request = state.preview();
  state.session.value = 2;
  pending.resolve(batch()); await request; await flush();
  assert.equal(state.current.value, null);
  assert.equal(state.busy.value, false);
  state.scope.stop();
});

test("closing the view or switching servers ignores late apply results and refresh callbacks", async () => {
  for (const mode of ["close", "server"]) {
    const pending = deferred();
    const state = fixture({ applyMemoryConsolidation: () => pending.promise });
    await flush(); await state.preview(); state.toggle(0);
    const request = state.apply();
    if (mode === "close") state.scope.stop();
    else state.setServer("http://two.invalid");
    pending.resolve(batch(1, "applied")); await request;
    assert.equal(state.changed(), 0);
    assert.equal(state.current.value.status, "preview");
    state.scope.stop();
  }
});

test("a stale-source rejection keeps the review visible and displays the backend reason", async () => {
  const state = fixture({ applyMemoryConsolidation: async () => { throw new Error('[API Error 409] /sessions/1: {"detail":"来源记忆已经改变，请重新预览后再应用"}'); } });
  await flush(); await state.preview(); state.toggle(0); await state.apply();
  assert.equal(state.current.value.status, "preview");
  assert.match(state.error.value, /来源记忆已经改变/);
  assert.equal(state.changed(), 0);
  state.scope.stop();
});

test("switching servers cannot apply an old batch even when the new server has the same IDs", async () => {
  let applies = 0;
  const state = fixture({ applyMemoryConsolidation: async () => { applies++; return batch(1, "applied"); } });
  await flush(); await state.preview(); state.toggle(0);
  state.setServer("http://two.invalid");
  await state.apply();
  assert.equal(applies, 0);
  assert.equal(state.current.value, null);
  state.scope.stop();
});

test("older applied records remain reachable through history pagination", async () => {
  const calls = [];
  const state = fixture({ getMemoryConsolidations: async (_id, offset = 0) => {
    calls.push(offset);
    return { items: offset ? [batch(1, "applied")] : [batch(2)], has_more: !offset };
  } });
  await flush(); await state.loadMoreHistory();
  assert.deepEqual(calls, [0, 1]);
  state.choose(state.batches.value[1]);
  assert.equal(state.current.value.status, "applied");
  state.scope.stop();
});

test("repeated clicks cannot submit duplicate apply requests", async () => {
  const pending = deferred(); let calls = 0;
  const state = fixture({ applyMemoryConsolidation: () => { calls++; return pending.promise; } });
  await flush(); await state.preview(); state.toggle(0);
  const first = state.apply(); await state.apply();
  assert.equal(calls, 1);
  pending.resolve(batch(1, "applied")); await first;
  state.scope.stop();
});

test("next batch carries its cursor and saved previews can be reopened", async () => {
  const cursors = [];
  const state = fixture({ previewMemoryConsolidation: async (id, after) => { cursors.push([id, after]); return batch(after ? 2 : 1); } });
  await flush(); await state.preview(); await state.preview(80);
  assert.deepEqual(cursors, [[1, 0], [1, 80]]);
  state.choose(state.batches.value[1]);
  assert.equal(state.current.value.id, 1);
  assert.equal(state.selected.value.length, 0);
  state.scope.stop();
});

test("consolidation API uses domain routes, explicit group payloads and a model request timeout", async () => {
  const calls = [];
  const load = createLoader({ mocks: { "./mock/memories": {}, "./config": { USE_MOCK: false, request: async (...args) => { calls.push(args); return batch(); } } } });
  const api = load("api/memories.ts");
  await api.getMemoryConsolidations(2); await api.previewMemoryConsolidation(2, 80);
  await api.applyMemoryConsolidation(2, 7, [0]); await api.undoMemoryConsolidation(2, 7);
  assert.deepEqual(calls.map(call => call[0]), ["/sessions/2/memory-consolidations?limit=10&offset=0", "/sessions/2/memory-consolidations/preview",
    "/sessions/2/memory-consolidations/7/apply", "/sessions/2/memory-consolidations/7/undo"]);
  assert.deepEqual(JSON.parse(calls[1][1].body), { after_id: 80 });
  assert.deepEqual(JSON.parse(calls[2][1].body), { group_ids: [0] });
  assert.equal(calls[1][1].timeout, 180000);
});

test("offline mode explicitly declines model generation and never mutates stored memories", async () => {
  const load = createLoader({ mocks: { "./mock/memories": {}, "./config": { USE_MOCK: true } } });
  const api = load("api/memories.ts");
  assert.equal((await api.getMemoryConsolidations(1)).items.length, 0);
  await assert.rejects(api.previewMemoryConsolidation(1), /离线/);
  await assert.rejects(api.applyMemoryConsolidation(1, 1, [0]), /离线/);
  await assert.rejects(api.undoMemoryConsolidation(1, 1), /离线/);
});
