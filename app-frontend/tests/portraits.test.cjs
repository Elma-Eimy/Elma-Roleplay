const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, reactive, effectScope, nextTick } = require("vue");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");
const flush = async () => { for (let i = 0; i < 5; i++) await nextTick(); };
const snapshot = id => ({ session_id: id, portrait_id: id, image_path: `image${id}.png`, revision: "r1" });

test("portrait requests use domain endpoints, revision and authenticated uploads", async () => {
  const calls = [], uploads = [];
  const api = createLoader({ mocks: { "./config": {
    USE_MOCK: false, request: async (...args) => { calls.push(args); return snapshot(1); },
    getBaseUrl: () => "https://server.test", getHeaders: () => ({ "X-API-Key": "test-key" }),
  } }, globals: { uni: { uploadFile: options => { uploads.push(options); options.success({ statusCode: 200, data: '{"id":1}' }); } } } })("api/portraits.ts");
  await api.getPortraits(5);
  await api.getPortraitSelection(3);
  await api.setPortraitSelection(3, null, "revision");
  await api.renamePortrait(5, 8, "便服");
  await api.deletePortrait(5, 8);
  await api.uploadPortrait(5, "temp.png");
  assert.equal(calls[0][0], "/characters/5/portraits");
  assert.equal(calls[1][0], "/sessions/3/portrait");
  assert.deepEqual(JSON.parse(calls[2][1].body), { portrait_id: null, expected_revision: "revision" });
  assert.equal(calls[2][1].method, "PUT");
  assert.equal(calls[4][0], "/characters/5/portraits/8/delete");
  assert.equal(uploads[0].url, "https://server.test/characters/5/portraits");
  assert.equal(uploads[0].header["X-API-Key"], "test-key");
  assert.equal(uploads[0].filePath, "temp.png");
});

test("offline portrait operations explicitly reject instead of claiming persistence", async () => {
  const api = createLoader({ mocks: { "./config": { USE_MOCK: true } } })("api/portraits.ts");
  await assert.rejects(api.getPortraits(1), /离线模式/);
  await assert.rejects(api.setPortraitSelection(1, 2, "revision"), /离线模式/);
  await assert.rejects(api.uploadPortrait(1, "temp.png"), /离线模式/);
});

function fixture(getPortraitSelection) {
  const id = ref(1), timeline = ref("1");
  let server = "https://one.test";
  const load = createLoader({ mocks: {
    "@/api/config": { getBaseUrl: () => server, USE_MOCK: false },
    "@/api/portraits": { getPortraitSelection },
  } });
  const scope = effectScope();
  const state = scope.run(() => load("composables/usePortraitSelection.ts").usePortraitSelection(() => id.value, () => timeline.value));
  return { ...state, id, timeline, scope, setServer: value => { server = value; } };
}

test("late portrait load cannot overwrite another story or an unloaded page", async () => {
  const pending = deferred();
  const state = fixture(id => id === 1 ? pending.promise : Promise.resolve(snapshot(id)));
  state.id.value = 2;
  await flush();
  pending.resolve(snapshot(1));
  await flush();
  assert.equal(state.selection.value.session_id, 2);
  const late = deferred();
  const closed = fixture(() => late.promise);
  closed.scope.stop();
  late.resolve(snapshot(1));
  await flush();
  assert.equal(closed.selection.value, null);
  state.scope.stop();
});

test("latest timeline refresh wins and a changed server invalidates old results", async () => {
  const first = deferred(), second = deferred();
  let count = 0;
  const state = fixture(() => ++count === 1 ? first.promise : second.promise);
  state.timeline.value = "different-candidate";
  await flush();
  second.resolve(snapshot(2));
  await flush();
  first.resolve(snapshot(1));
  await flush();
  assert.equal(state.selection.value.portrait_id, 2);
  state.scope.stop();
  const pending = deferred();
  const changed = fixture(() => pending.promise);
  changed.setServer("https://two.test");
  pending.resolve(snapshot(1));
  await flush();
  assert.equal(changed.selection.value, null);
  changed.scope.stop();
});

// 执行组件的实际 setup 脚本，覆盖面板独立于聊天背景的加载和写入时序。
function panelFixture(api = {}) {
  const filename = path.resolve(__dirname, "../src/components/character/CharacterPortraitPanel.vue");
  const script = fs.readFileSync(filename, "utf8").match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];
  const code = ts.transpileModule(script + "\nexport { selection, busy, error, choose };", {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const props = reactive({ characterId: 1, sessionId: 1, timeline: "candidate-A", disabled: false });
  const events = [], scope = effectScope(), module = { exports: {} };
  const mocks = {
    vue: require("vue"),
    "@/api/config": { getBaseUrl: () => "https://server.test" },
    "@/api/characters": { getAvatarUrl: value => value },
    "@/utils/characterCard": { cardImportError: String },
    "@/api/portraits": {
      getPortraits: async () => ({ portraits: [] }),
      getPortraitSelection: async id => snapshot(id),
      setPortraitSelection: async id => snapshot(id),
      ...api,
    },
  };
  scope.run(() => vm.runInNewContext(code, {
    exports: module.exports, module,
    require: name => { if (!(name in mocks)) throw new Error(`Unexpected import: ${name}`); return mocks[name]; },
    defineProps: () => props, defineEmits: () => event => events.push(event),
  }, { filename }));
  return { ...module.exports, props, events, scope };
}

test("panel replaces an in-flight read when the timeline changes and ignores its late result", async () => {
  const first = deferred(), second = deferred();
  let reads = 0;
  const panel = panelFixture({ getPortraitSelection: () => ++reads === 1 ? first.promise : second.promise });
  try {
    panel.props.timeline = "candidate-B";
    await flush();
    assert.equal(reads, 2);
    second.resolve({ ...snapshot(2), revision: "revision-B" });
    await flush();
    assert.equal(panel.selection.value.revision, "revision-B");
    first.resolve({ ...snapshot(1), revision: "revision-A" });
    await flush();
    assert.equal(panel.selection.value.revision, "revision-B");
    assert.equal(panel.busy.value, false);
  } finally { panel.scope.stop(); }
});

test("panel queues timeline refresh during a write without unlocking or losing the write completion", async () => {
  const write = deferred();
  let reads = 0;
  const panel = panelFixture({
    getPortraitSelection: async () => ({ ...snapshot(1), revision: `revision-${++reads}` }),
    setPortraitSelection: () => write.promise,
  });
  try {
    await flush();
    const pendingWrite = panel.choose(2);
    panel.props.timeline = "candidate-B";
    await flush();
    assert.equal(reads, 1);
    assert.equal(panel.busy.value, true);
    write.resolve(snapshot(2));
    await pendingWrite;
    await flush();
    assert.equal(reads, 2);
    assert.equal(panel.selection.value.revision, "revision-2");
    assert.deepEqual(panel.events, ["changed"]);
    assert.equal(panel.busy.value, false);
  } finally { panel.scope.stop(); }
});

test("panel refreshes after a failed write with a pending timeline change and retains the error", async () => {
  const write = deferred();
  let reads = 0;
  const panel = panelFixture({
    getPortraitSelection: async () => ({ ...snapshot(1), revision: `revision-${++reads}` }),
    setPortraitSelection: () => write.promise,
  });
  try {
    await flush();
    const pendingWrite = panel.choose(2);
    panel.props.timeline = "generation-finished";
    await flush();
    write.reject(new Error("409 revision conflict"));
    await pendingWrite;
    await flush();
    assert.equal(reads, 2);
    assert.equal(panel.selection.value.revision, "revision-2");
    assert.match(panel.error.value, /409 revision conflict/);
    assert.equal(panel.busy.value, false);
    assert.deepEqual(panel.events, []);
  } finally { panel.scope.stop(); }
});

test("a late panel write after switching stories cannot refresh or unlock the new story", async () => {
  const write = deferred(), newStory = deferred();
  const panel = panelFixture({
    getPortraitSelection: id => id === 1 ? Promise.resolve(snapshot(1)) : newStory.promise,
    setPortraitSelection: () => write.promise,
  });
  try {
    await flush();
    const pendingWrite = panel.choose(2);
    panel.props.sessionId = 2;
    await flush();
    write.resolve(snapshot(2));
    await pendingWrite;
    await flush();
    assert.equal(panel.selection.value, null);
    assert.equal(panel.busy.value, true);
    assert.deepEqual(panel.events, []);
    newStory.resolve(snapshot(2));
    await flush();
    assert.equal(panel.selection.value.session_id, 2);
    assert.equal(panel.busy.value, false);
  } finally { panel.scope.stop(); }
});
