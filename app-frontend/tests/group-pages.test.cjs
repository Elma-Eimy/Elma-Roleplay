const test = require("node:test");
const assert = require("node:assert/strict");
const { effectScope } = require("vue");
const fs = require("node:fs");
const path = require("node:path");
const { createLoader, deferred, sourceRoot } = require("./helpers/load-ts.cjs");

const plain = value => JSON.parse(JSON.stringify(value));
const character = id => ({ id, name: `actor${id}`, avatar_path: "" });
const group = (id, title = `group${id}`) => ({ kind: "group", session_id: id, title, members: [], can_generate: false });
const page = (items = [], more = false, offset = 0) => ({ sessions: items, total: items.length, has_more: more, offset, limit: 20 });
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function fixture(kind, overrides = {}, mock = false, platform = "H5") {
  let server = "https://a.invalid";
  const listeners = new Set();
  const navigations = [];
  const calls = [];
  const storage = new Map();
  const api = {
    getGroupSessions: async () => page(), getGroupSession: async id => group(id),
    getGroupRounds: async () => ({ rounds: [], total: 0, limit: 20, offset: 0, has_more: false }),
    createGroupSession: async value => { calls.push(value); return group(50); },
    deleteGroupSession: async id => { calls.push(id); return { deleted_session_id: id }; },
    ...overrides,
  };
  const load = createLoader({ platform, globals: { uni: {
    getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, plain(value)),
    removeStorageSync: key => storage.delete(key),
  } }, mocks: {
    "@/api/config": { getBaseUrl: () => server, USE_MOCK: mock },
    "@/api/characters": { getCharacters: overrides.getCharacters ?? (async () => ({ characters: [1, 2, 3, 4].map(character) })) },
    "@/api/sessions": { getSessions: overrides.getSessions ?? (async () => page()) },
    "@/api/groupSessions": api,
    "@/api/portraits": { getPortraits: async () => ({ portraits: [], total: 0, has_more: false }) },
    "@/utils/connectionEvents": { onServerChange: callback => { listeners.add(callback); return () => listeners.delete(callback); } },
  } });
  const scope = effectScope();
  const hooks = scope.run(() => load("composables/useGroupSessions.ts"));
  const state = scope.run(() => kind === "create" ? hooks.useGroupSessionCreate(value => navigations.push(value.session_id))
    : kind === "detail" ? hooks.useGroupSessionDetail(() => navigations.push("deleted")) : hooks.useGroupSessionList());
  const setServer = value => { server = value; for (const listener of [...listeners]) listener(); };
  return { state, scope, setServer, navigations, calls, listeners };
}
function fill(f) {
  f.state.title.value = "group";
  f.state.toggleCharacter(character(1));
  f.state.toggleCharacter(character(2));
}

const roundPage = (items = [], more = false, offset = 0) => ({ rounds: items, total: 3,
  limit: 20, offset, has_more: more });
const round = id => ({ round_id: id, round_index: id, candidate_id: id,
  status: "failed", confirmed: false, user_content: "sample", utterances: [] });

test("round pagination preserves failure prefixes and retries the failed page", async () => {
  let fail = true;
  const offsets = [];
  const f = fixture("detail", { getGroupRounds: async (id, limit, offset) => {
    offsets.push(offset);
    if (!offset) return roundPage([round(3)], true);
    if (fail) { fail = false; throw new Error("network failed"); }
    return roundPage([round(3), round(2)], true, offset);
  } });
  f.state.setSessionId(1); f.state.show(); await flush();
  await f.state.loadRounds(true);
  assert.match(f.state.roundsError.value, /network failed/);
  assert.deepEqual(plain(f.state.rounds.value.map(item => item.round_id)), [3]);
  await f.state.retryRounds();
  assert.deepEqual(offsets, [0, 1, 1]);
  assert.deepEqual(plain(f.state.rounds.value.map(item => item.round_id)), [3, 2]);
  await f.state.loadRounds(true);
  assert.equal(offsets.at(-1), 3);
  f.scope.stop();
});

test("failed round refresh retries offset zero while retaining the old view", async () => {
  const offsets = []; let reads = 0;
  const f = fixture("detail", { getGroupRounds: async (_, limit, offset) => {
    offsets.push(offset); if (++reads === 2) throw new Error("refresh failed");
    return roundPage([round(reads)], true);
  } });
  f.state.setSessionId(1); f.state.show(); await flush();
  await f.state.loadRounds();
  assert.equal(f.state.rounds.value[0].round_id, 1);
  await f.state.retryRounds();
  assert.deepEqual(offsets, [0, 0, 0]);
  assert.equal(f.state.rounds.value[0].round_id, 3);
  f.scope.stop();
});

test("detail refresh cannot be displaced by a concurrent round pagination read", async () => {
  const refresh = deferred(); let detailReads = 0;
  const offsets = [];
  const f = fixture("detail", {
    getGroupSession: async id => ++detailReads === 1 ? group(id) : refresh.promise,
    getGroupRounds: async (_, limit, offset) => {
      offsets.push(offset);
      return roundPage([round(offsets.length === 1 ? 1 : 2)], true, offset);
    },
  });
  f.state.setSessionId(1); f.state.show(); await flush();
  const updating = f.state.load();
  await f.state.loadRounds(true);
  assert.deepEqual(offsets, [0]);
  refresh.resolve(group(1)); await updating; await flush();
  assert.deepEqual(offsets, [0, 0]);
  assert.deepEqual(plain(f.state.rounds.value.map(item => item.round_id)), [2]);
  f.scope.stop();
});

for (const change of ["story", "server", "hide"]) {
  test(`late round history cannot refill state after ${change}`, async () => {
    const pending = deferred(); let reads = 0;
    const f = fixture("detail", { getGroupRounds: () => ++reads === 1 ? pending.promise : Promise.resolve(roundPage([round(2)])) });
    f.state.setSessionId(1); f.state.show(); await flush();
    if (change === "story") { f.state.setSessionId(2); await f.state.load(); await flush(); }
    if (change === "server") f.setServer("https://b.invalid");
    if (change === "hide") { f.state.hide(); f.state.show(); await flush(); }
    pending.resolve(roundPage([round(1)])); await flush();
    assert.deepEqual(plain(f.state.rounds.value.map(item => item.round_id)), ["story", "hide"].includes(change) ? [2] : []);
    assert.equal(f.state.loadingRounds.value, false);
    f.scope.stop();
  });
}

test("group pages keep the home entry and use the independent group flow", () => {
  const routes = JSON.parse(fs.readFileSync(path.join(sourceRoot, "pages.json"), "utf8"));
  assert.equal(routes.pages[0].path, "pages/index/index");
  for (const name of ["index", "create", "detail"]) {
    assert.ok(routes.pages.some(page => page.path === `pages/group/${name}`));
  }
  const home = fs.readFileSync(path.join(sourceRoot, "pages/index/index.vue"), "utf8");
  assert.match(home, /@tap="goToGroups"/);
  const detail = fs.readFileSync(path.join(sourceRoot, "pages/group/detail.vue"), "utf8");
  assert.doesNotMatch(detail, /sendMessage|chatStore/);
  assert.match(detail, /state.command\('send'\)/);
});

for (const platform of ["H5", "APP-PLUS", "MP-WEIXIN"]) {
  test(`${platform}: duplicate submission is blocked and payload is frozen while the request runs`, async () => {
    const pending = deferred(), requests = [];
    const f = fixture("create", { createGroupSession: value => { requests.push(value); return pending.promise; } }, false, platform);
    f.state.show(); await flush(); fill(f);
    const saving = f.state.submit();
    await f.state.submit();
    f.state.title.value = "changed locally";
    f.state.toggleCharacter(character(3));
    assert.equal(requests.length, 1);
    assert.equal(requests[0].title, "group");
    assert.equal(f.state.members.value.length, 2);
    pending.resolve(group(50)); await saving;
    assert.deepEqual(f.navigations, [50]);
    await f.state.submit(); assert.equal(requests.length, 1);
    f.scope.stop(); assert.equal(f.listeners.size, 0);
  });
}

test("validation retains the draft, caps members and requires an explicit snapshot source", async () => {
  const f = fixture("create"); f.state.show(); await flush();
  await f.state.submit(); assert.equal(f.calls.length, 0);
  fill(f);
  f.state.toggleCharacter(character(3)); f.state.toggleCharacter(character(4));
  assert.equal(f.state.members.value.length, 3);
  const member = f.state.members.value[0];
  f.state.setMode(member, "single_snapshot"); await flush();
  assert.match(f.state.validation.value, /来源单聊/);
  await f.state.submit(); assert.equal(f.calls.length, 0);
  f.scope.stop();
});

test("a removed and re-added member cannot receive an old source list", async () => {
  const pending = deferred();
  const f = fixture("create", { getSessions: () => pending.promise });
  f.state.show(); await flush(); fill(f);
  const old = f.state.members.value[0]; f.state.setMode(old, "single_snapshot");
  f.state.toggleCharacter(character(1)); f.state.toggleCharacter(character(1));
  pending.resolve(page([{ id: 99, title: "old source" }])); await flush();
  const current = f.state.members.value.find(member => member.character.id === 1);
  assert.equal(current.mode, "card"); assert.equal(current.sources.length, 0);
  f.scope.stop();
});

test("snapshot source pagination is scoped to its member and serializes the selected story", async () => {
  const requests = [];
  const f = fixture("create", { getSessions: async (id, limit, offset, last) => {
    requests.push([id, limit, offset, last]);
    return { ...page([{ id: offset + 10, title: `source ${offset}` }]), has_more: offset === 0 };
  } });
  f.state.show(); await flush(); fill(f);
  const member = f.state.members.value[0]; f.state.setMode(member, "single_snapshot"); await flush();
  await f.state.loadSources(member, true);
  member.sourceSessionId = member.sources[1].id;
  await f.state.submit();
  assert.deepEqual(requests, [[1, 20, 0, false], [1, 20, 1, false]]);
  assert.deepEqual(plain(f.calls[0].members[0].origin), { mode: "single_snapshot", session_id: 11 });
  f.scope.stop();
});

for (const more of [false, true]) {
  test(`interrupted source ${more ? "pagination" : "initial loading"} resumes without accepting the old reply`, async () => {
    const old = deferred(), resumed = deferred(), offsets = [];
    const f = fixture("create", { getSessions: async (_, limit, offset) => {
      offsets.push(offset);
      if (more && offsets.length === 1) return page([{ id: 10, title: "selected source" }], true);
      return offsets.length === (more ? 2 : 1) ? old.promise : resumed.promise;
    } });
    f.state.show(); await flush(); fill(f);
    const member = f.state.members.value[0]; f.state.setMode(member, "single_snapshot");
    if (more) {
      await flush(); member.sourceSessionId = 10;
      void f.state.loadSources(member, true);
    }
    f.state.hide(); f.state.hide(); f.state.show();
    assert.deepEqual(offsets, more ? [0, 1, 1] : [0, 0]);
    assert.equal(member.loadingSources, true);
    old.resolve(page([{ id: 99, title: "stale source" }])); await flush();
    assert.equal(member.loadingSources, true);
    assert.deepEqual(plain(member.sources.map(source => source.id)), more ? [10] : []);
    resumed.resolve(page([{ id: 11, title: "resumed source" }], false, more ? 1 : 0)); await flush();
    assert.equal(member.loadingSources, false);
    assert.equal(member.pendingSourcePage, null);
    assert.deepEqual(plain(member.sources.map(source => source.id)), more ? [10, 11] : [11]);
    assert.equal(member.sourceSessionId, more ? 10 : null);
    f.state.hide(); f.state.show(); await flush();
    assert.equal(offsets.length, more ? 3 : 2);
    f.scope.stop();
  });
}

test("confirming an unchanged origin mode preserves pending reads, selection and pagination", async () => {
  const pending = deferred(); let reads = 0;
  const f = fixture("create", { getSessions: () => { reads++; return pending.promise; } });
  f.state.show(); await flush(); fill(f);
  const member = f.state.members.value[0]; f.state.setMode(member, "single_snapshot");
  f.state.setMode(member, "single_snapshot");
  assert.equal(reads, 1); assert.equal(member.loadingSources, true);
  pending.resolve(page([{ id: 11, title: "selected source" }], true)); await flush();
  member.sourceSessionId = 11;
  f.state.setMode(member, "single_snapshot"); await flush();
  assert.equal(reads, 1); assert.equal(member.sourceSessionId, 11);
  assert.equal(member.sourceOffset, 1); assert.equal(member.hasMoreSources, true);
  assert.deepEqual(plain(member.sources.map(source => source.id)), [11]);
  f.state.setMode(member, "card");
  assert.equal(member.sourceSessionId, null); assert.equal(member.sources.length, 0);
  f.scope.stop();
});

test("known validation failure permits correction while uncertain creation never resends", async () => {
  for (const [failure, uncertain] of [[new Error('[API Error 422] /group-sessions: {"detail":"bad source"}'), false], [new Error("timeout"), true]]) {
    let calls = 0;
    const f = fixture("create", { createGroupSession: async () => { calls++; throw failure; } });
    f.state.show(); await flush(); fill(f);
    await f.state.submit();
    assert.equal(f.state.uncertain.value, uncertain);
    assert.equal(f.state.title.value, "group");
    if (uncertain) { await f.state.submit(); assert.equal(calls, 1); }
    else assert.match(f.state.error.value, /bad source/);
    f.scope.stop();
  }
});

test("hiding during creation marks the result uncertain and ignores success or failure after return", async () => {
  for (const failed of [false, true]) {
    const pending = deferred();
    const f = fixture("create", { createGroupSession: () => pending.promise });
    f.state.show(); await flush(); fill(f); const saving = f.state.submit();
    f.state.hide(); f.state.show();
    if (failed) pending.reject(new Error("late")); else pending.resolve(group(50));
    await saving;
    assert.equal(f.state.uncertain.value, true);
    assert.equal(f.navigations.length, 0);
    assert.equal(f.state.created.value, null);
    f.scope.stop();
  }
});

test("A→B→A clears creation data and old completion cannot navigate or unlock a new submit", async () => {
  const old = deferred(), current = deferred(); let count = 0;
  const f = fixture("create", { createGroupSession: () => (++count === 1 ? old : current).promise });
  f.state.show(); await flush(); fill(f); const savingOld = f.state.submit();
  f.setServer("https://b.invalid"); f.setServer("https://a.invalid"); await flush();
  assert.equal(f.state.members.value.length, 0); assert.equal(f.state.title.value, "");
  fill(f); const savingCurrent = f.state.submit();
  old.resolve(group(50)); await savingOld;
  assert.equal(f.state.submitting.value, true); assert.equal(f.navigations.length, 0);
  current.resolve(group(51)); await savingCurrent;
  assert.deepEqual(f.navigations, [51]); f.scope.stop();
});

test("character reads are invalidated on server changes and offline mode never offers snapshots", async () => {
  const pending = deferred(); let reads = 0;
  const f = fixture("create", { getCharacters: () => ++reads === 1 ? pending.promise : Promise.resolve({ characters: [character(3)] }) }, true);
  f.state.show(); f.setServer("https://b.invalid"); await flush();
  pending.resolve({ characters: [character(1)] }); await flush();
  assert.deepEqual(plain(f.state.characters.value.map(item => item.id)), [3]);
  assert.equal(f.state.supportsSnapshots, false);
  f.state.toggleCharacter(character(3)); const member = f.state.members.value[0];
  f.state.setMode(member, "single_snapshot"); assert.equal(member.mode, "card");
  f.scope.stop();
});

test("list pagination deduplicates rows but advances by the server page and preserves data on errors", async () => {
  const offsets = [];
  const f = fixture("list", { getGroupSessions: async (_, offset) => {
    offsets.push(offset);
    if (offset === 0) return page([group(1)], true, 0);
    if (offset === 1) return page([group(1), group(2)], true, 1);
    throw new Error("network failed");
  } });
  f.state.show(); await flush(); await f.state.load(true); await f.state.load(true);
  assert.deepEqual(offsets, [0, 1, 3]);
  assert.deepEqual(plain(f.state.groups.value.map(item => item.session_id)), [1, 2]);
  assert.match(f.state.error.value, /network failed/); f.scope.stop();
});

test("list stale replies after A→B→A or hide cannot clear the current request's busy state", async () => {
  const old = deferred(), next = deferred(); let reads = 0;
  const f = fixture("list", { getGroupSessions: () => (++reads === 1 ? old : next).promise });
  f.state.show(); f.setServer("https://b.invalid"); f.setServer("https://a.invalid");
  old.resolve(page([group(1)])); await flush();
  assert.equal(f.state.loading.value, true); assert.equal(f.state.groups.value.length, 0);
  next.resolve(page([group(2)])); await flush();
  assert.deepEqual(plain(f.state.groups.value.map(item => item.session_id)), [2]);
  f.scope.stop(); assert.equal(f.listeners.size, 0);
});

test("details never reuse a same-number story after changing servers", async () => {
  const pending = deferred(); let reads = 0;
  const f = fixture("detail", { getGroupSession: () => { reads++; return pending.promise; } });
  f.state.setSessionId(1); f.state.show(); f.setServer("https://b.invalid"); f.setServer("https://a.invalid");
  pending.resolve(group(1)); await flush();
  assert.equal(f.state.group.value, null); assert.equal(f.state.serverChanged.value, true);
  assert.equal(reads, 1); f.scope.stop();
});

test("invalid detail IDs return to selection without issuing an invalid request", async () => {
  let reads = 0;
  const f = fixture("detail", { getGroupSession: async id => { reads++; return group(id); } });
  f.state.setSessionId(Number.NaN); f.state.show(); await flush();
  assert.equal(reads, 0); assert.equal(f.state.needsSelection.value, true);
  assert.match(f.state.error.value, /编号无效/);
  f.scope.stop();
});

test("a stale delete confirmation cannot send POST and a stale delete completion cannot navigate", async () => {
  const confirmation = deferred(), removal = deferred();
  let deletes = 0;
  const f = fixture("detail", { deleteGroupSession: () => { deletes++; return removal.promise; } });
  f.state.setSessionId(1); f.state.show(); await flush();
  const asking = f.state.remove(() => confirmation.promise);
  f.state.setSessionId(2); await f.state.load();
  confirmation.resolve(true); await asking;
  assert.equal(deletes, 0); assert.equal(f.state.deleting.value, false);
  const deleting = f.state.remove(async () => true); await flush();
  assert.equal(deletes, 1);
  f.state.hide(); f.state.show(); await flush();
  removal.resolve({ deleted_session_id: 2 }); await deleting;
  assert.equal(f.navigations.length, 0); f.scope.stop();
});

test("leaving a scope unsubscribes and prevents pending writes from producing UI effects", async () => {
  const pending = deferred();
  const f = fixture("create", { createGroupSession: () => pending.promise });
  f.state.show(); await flush(); fill(f); const saving = f.state.submit();
  f.scope.stop(); pending.resolve(group(50)); await saving;
  assert.equal(f.navigations.length, 0); assert.equal(f.listeners.size, 0);
});

test("detail refresh failure preserves the unsent round draft", async () => {
  let fails = false;
  const f = fixture("detail", { getGroupSession: async id => { if (fails) throw new Error('offline'); return group(id); } });
  f.state.setSessionId(1); f.state.show(); await flush(); f.state.draft.value = 'unfinished draft';
  fails = true; await f.state.load(); assert.equal(f.state.group.value, null);
  assert.equal(f.state.draft.value, 'unfinished draft');
  fails = false; await f.state.load(); await flush(); assert.equal(f.state.draft.value, 'unfinished draft'); f.scope.stop();
});

test("pending round operations block deletion and late POST remains invalid after returning", async () => {
  const post = deferred(); let deletes = 0, queries = 0;
  const f = fixture("detail", {
    getGroupRounds: async () => ({ ...roundPage(), can_generate: true, current: {
      group_revision: 0, latest: null, active_operation: null,
      capabilities: { can_send: true, can_regenerate: false, can_select: false, can_discard: false },
    } }),
    sendGroupRound: () => post.promise,
    getGroupRequest: async () => { queries++; throw new Error('[API Error 404] unknown'); },
    deleteGroupSession: async () => { deletes++; },
  });
  f.state.setSessionId(1); f.state.show(); await flush(); f.state.draft.value = 'hello';
  const saving = f.state.command('send'); await f.state.remove(async () => true); assert.equal(deletes, 0);
  f.state.hide(); f.state.show(); await flush();
  post.resolve({ status: 'queued', accepted: { group_revision: 999 } }); await saving; await flush();
  assert.equal(queries, 1); assert.equal(f.state.pending.value.kind, 'send');
  assert.equal(f.state.current.value.group_revision, 0); assert.equal(f.state.submitting.value, false);
  await f.state.remove(async () => true); assert.equal(deletes, 0); f.scope.stop();
});

test("delete waits for initial history and recovery lookup, including after a failed history read", async () => {
  const pending = deferred(); let deletes = 0, fail = false;
  const f = fixture('detail', { getGroupRounds: () => fail ? Promise.reject(new Error('offline')) : pending.promise,
    deleteGroupSession: async () => { deletes++; } });
  f.state.setSessionId(1); f.state.show(); await flush();
  await f.state.remove(async () => true); assert.equal(deletes, 0);
  pending.reject(new Error('offline')); await flush(); fail = true;
  await f.state.remove(async () => true); assert.equal(deletes, 0); f.scope.stop();
});

test("deleting after history recovery is checked clears saved rounds", async () => {
  const f = fixture('detail', { getGroupRounds: async () => roundPage([round(1)]) });
  f.state.setSessionId(1); f.state.show(); await flush();
  await f.state.remove(async () => true);
  assert.equal(f.state.group.value, null); assert.equal(f.state.rounds.value.length, 0);
  assert.deepEqual(f.navigations, ['deleted']); f.scope.stop();
});
