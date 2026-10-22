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
  assert.deepEqual(JSON.parse(calls[1][1].body), { after_id: 80, mode: "full" });
  assert.deepEqual(JSON.parse(calls[2][1].body), { group_ids: [0], expected_revision: 0 });
  assert.equal(calls[1][1].timeout, 180000);
});

test("offline mode explicitly declines model generation and never mutates stored memories", async () => {
  const load = createLoader({ mocks: { "./mock/memories": {}, "./config": { USE_MOCK: true } } });
  const api = load("api/memories.ts");
  assert.equal((await api.getMemoryConsolidations(1)).items.length, 0);
  await assert.rejects(api.previewMemoryConsolidation(1), /离线/);
  await assert.rejects(api.applyMemoryConsolidation(1, 1, [0]), /离线/);
  await assert.rejects(api.undoMemoryConsolidation(1, 1), /离线/);
  await assert.rejects(api.reviewMemoryConsolidationGroup(1, 1, 0, {}), /离线/);
});

test("review saves edits with revision, clears selection and prevents ignored or conflicting selection", async () => {
  const calls = [];
  const state = fixture({ reviewMemoryConsolidationGroup: async (...args) => {
    calls.push(args);
    const saved = batch(); saved.review_revision = 1;
    saved.groups[0] = { ...saved.groups[0], content: args[3].content, ignored: args[3].ignored, ignore_reason: args[3].ignore_reason };
    return saved;
  } });
  await flush(); await state.preview(); state.toggle(0); state.editGroup(0);
  state.draftContent.value = "审阅后保留的完整经历";
  state.draftIgnored.value = true; state.draftReason.value = "暂不整理";
  await state.apply(); assert.equal(state.changed(), 0);
  await state.saveReview();
  assert.equal(calls[0][3].expected_revision, 0);
  assert.equal(state.current.value.review_revision, 1);
  assert.equal(state.editingId.value, null);
  assert.equal(state.selected.value.length, 0);
  state.toggle(0); assert.equal(state.selected.value.length, 0);
  state.current.value.groups[0].ignored = false;
  state.current.value.groups[0].conflict = "来源已改变";
  state.toggle(0); assert.equal(state.selected.value.length, 0);
  state.scope.stop();
});

test("failed review retains draft and late review cannot overwrite another story", async () => {
  const pending = deferred();
  const state = fixture({ reviewMemoryConsolidationGroup: () => pending.promise });
  await flush(); await state.preview(); state.editGroup(0);
  state.draftContent.value = "需要保留的用户编辑正文";
  const saving = state.saveReview();
  pending.reject(new Error("审阅内容已更新")); await saving;
  assert.equal(state.editingId.value, 0);
  assert.equal(state.draftContent.value, "需要保留的用户编辑正文");
  assert.match(state.error.value, /已更新/);
  state.scope.stop();
  for (const mode of ["session", "server", "close"]) {
    const request = deferred();
    const other = fixture({ reviewMemoryConsolidationGroup: () => request.promise });
    await flush(); await other.preview(); other.editGroup(0);
    const saving = other.saveReview();
    if (mode === "session") other.session.value = 2;
    else if (mode === "server") other.setServer("http://two.invalid");
    else other.scope.stop();
    request.resolve(batch(99)); await saving; await flush();
    assert.notEqual(other.current.value?.id, 99);
    assert.equal(other.changed(), 0); other.scope.stop();
  }
});

test("review API uses PUT and sends explicit review fields", async () => {
  const calls = [];
  const load = createLoader({ mocks: { "./mock/memories": {}, "./config": { USE_MOCK: false, request: async (...args) => { calls.push(args); return batch(); } } } });
  const input = { expected_revision: 2, content: "用户修改后的完整经历", ignored: false, ignore_reason: "已核对" };
  await load("api/memories.ts").reviewMemoryConsolidationGroup(2, 7, 0, input);
  assert.equal(calls[0][0], "/sessions/2/memory-consolidations/7/groups/0");
  assert.equal(calls[0][1].method, "PUT");
  assert.deepEqual(JSON.parse(calls[0][1].body), input);
});

test("apply sends saved revision and review validation keeps invalid text local", async () => {
  let applies = 0; let reviews = 0;
  const state = fixture({ previewMemoryConsolidation: async () => ({ ...batch(), review_revision: 3 }),
    applyMemoryConsolidation: async (_session, _batch, _groups, revision) => {
      applies++; assert.equal(revision, 3); return batch(1, "applied");
    }, reviewMemoryConsolidationGroup: async () => { reviews++; return batch(); } });
  await flush(); await state.preview(); state.editGroup(0);
  state.draftContent.value = "   "; await state.saveReview();
  assert.equal(reviews, 0); assert.equal(state.editingId.value, 0);
  state.editingId.value = null; state.toggle(0); await state.apply();
  assert.equal(applies, 1); state.scope.stop();
});

test("unsaved content, notes and ignore state survive group, history, refresh, preview and undo attempts", async () => {
  for (const field of ["draftContent", "draftReason", "draftIgnored"]) {
    let reads = 0; let previews = 0; let undos = 0;
    const saved = batch();
    saved.groups.push({ ...saved.groups[0], id: 1, content: "第二组原始建议" });
    const state = fixture({ getMemoryConsolidations: async () => { reads++; return { items: [saved] }; },
      previewMemoryConsolidation: async () => { previews++; return batch(2); },
      undoMemoryConsolidation: async () => { undos++; return batch(3, "undone"); } });
    await flush(); state.editGroup(0);
    state[field].value = field === "draftIgnored" ? true : "用户未保存的核对结果";
    const expected = [state.draftContent.value, state.draftReason.value, state.draftIgnored.value];
    state.editGroup(1);
    assert.equal(state.choose(batch(9)), false);
    await state.load(); await state.preview(); await state.preview(100); await state.undo(batch(3, "applied"));
    assert.equal(state.editingId.value, 0);
    assert.equal(state.current.value.id, 1);
    assert.deepEqual([state.draftContent.value, state.draftReason.value, state.draftIgnored.value], expected);
    assert.deepEqual([reads, previews, undos], [1, 0, 0]);
    assert.match(state.error.value, /未保存/);
    assert.equal(saved.groups[0].content, "合并的经历");
    state.editingId.value = null;
    assert.equal(state.choose(batch(9)), true);
    state.scope.stop();
  }
});

test("unchanged drafts can switch directly and dirty drafts never block context reset", async () => {
  const saved = batch();
  saved.groups.push({ ...saved.groups[0], id: 1, content: "第二组原始建议" });
  const state = fixture({ getMemoryConsolidations: async id => ({ items: [id === 1 ? saved : batch(2)] }) });
  await flush(); state.editGroup(0); state.editGroup(1);
  assert.equal(state.editingId.value, 1);
  state.draftContent.value = "第一故事未保存的正文";
  state.session.value = 2; await flush();
  assert.equal(state.editingId.value, null);
  assert.equal(state.current.value.id, 2);
  state.editGroup(0); state.draftReason.value = "旧服务器备注";
  state.setServer("http://two.invalid"); await state.load();
  assert.equal(state.editingId.value, null);
  assert.equal(state.error.value, "");
  state.scope.stop();
});

test("manual incremental scans reuse pending scope while full scans preserve the ID cursor", async () => {
  const calls = [];
  const state = fixture({ getMemoryConsolidations: async () => ({ items: [], scan_status: { eligible_count: 105, checked_count: 0, pending_count: 105 } }),
    previewMemoryConsolidation: async (id, after, mode) => {
      calls.push([id, after, mode]);
      return { ...batch(), scan_mode: mode, has_more: true, next_after_id: 100,
        scan_status: { eligible_count: 105, checked_count: 100, pending_count: 5 } };
    } });
  await flush(); assert.equal(calls.length, 0);
  assert.equal(state.scanStatus.value.pending_count, 105);
  await state.preview(0, "incremental");
  assert.equal(state.scanStatus.value.pending_count, 5);
  await state.continueScan();
  await state.preview(0, "full"); await state.continueScan();
  assert.deepEqual(calls, [[1, 0, "incremental"], [1, 0, "incremental"], [1, 0, "full"], [1, 100, "full"]]);
  state.scope.stop();
});

test("scan scope and progress remain unchanged on failed or late previews", async () => {
  const pending = deferred();
  const state = fixture({ getMemoryConsolidations: async () => ({ items: [], scan_status: { eligible_count: 2, checked_count: 0, pending_count: 2 } }),
    previewMemoryConsolidation: () => pending.promise });
  await flush();
  const saving = state.preview(0, "incremental");
  pending.reject(new Error("模型暂时不可用")); await saving;
  assert.equal(state.scanStatus.value.pending_count, 2);
  assert.equal(state.current.value, null);
  state.scope.stop();
});

test("preview API sends explicit incremental mode without moving the ID cursor", async () => {
  let body;
  const load = createLoader({ mocks: { "./mock/memories": {}, "./config": { USE_MOCK: false,
    request: async (_path, options) => { body = JSON.parse(options.body); return batch(); } } } });
  await load("api/memories.ts").previewMemoryConsolidation(2, 0, "incremental");
  assert.deepEqual(body, { after_id: 0, mode: "incremental" });
});
