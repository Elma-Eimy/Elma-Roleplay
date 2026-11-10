const test = require('node:test');
const assert = require('node:assert/strict');
const { createLoader, deferred } = require('./helpers/load-ts.cjs');

const plain = value => JSON.parse(JSON.stringify(value));
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const uuid = '12345678-1234-4234-8234-123456789012';
const latest = (cid = 11, revision = 4) => ({ round_id: 1, candidate_id: cid, candidate_revision: revision, confirmed: false });
const state = (revision = 0, selected = null, active = null) => ({ group_revision: revision, latest: selected,
  active_operation: active, capabilities: { can_send: !active, can_select: !!selected && !active,
    can_regenerate: !!selected && !active, can_discard: !!selected && !active } });
const round = (cid = 11) => ({ round_id: 1, round_index: 1, candidate_id: cid, revision: 4,
  confirmed: false, status: 'awaiting_confirmation', user_content: 'hello', utterances: [] });
const candidate = (id, status = 'awaiting_confirmation', selected = id === 11) => ({ candidate_id: id, version: id - 10,
  revision: 4, status, selected, can_select: status === 'awaiting_confirmation', can_resume: status === 'failed' });
const operation = (status = 'running') => ({ request_id: uuid, operation_id: 1, kind: 'send', status, revision: 1,
  round_id: 1, candidate_id: 11 });
const page = current => ({ can_generate: true, current, rounds: current.latest ? [round(current.latest.candidate_id)] : [],
  offset: 0, limit: 20, total: current.latest ? 1 : 0, has_more: false });

function fixture(overrides = {}, { platform = 'H5', storage = new Map(), mock = false, generation: resolveGeneration } = {}) {
  let server = 'https://a.invalid', id = 1, active = true, generation = 0, nextTimer = 0;
  const timers = new Map(), posts = [], queries = [];
  const model = { current: state(), rows: [candidate(11), candidate(12, 'failed', false)] };
  const submit = kind => async (sid, rid, body) => {
    posts.push({ sid, rid, body: plain(body ?? rid), kind });
    return { ...operation('queued'), kind, accepted: { round_id: 1, candidate_id: 11, group_revision: 1, candidate_revision: 0 } };
  };
  const api = {
    getGroupRounds: async () => page(model.current),
    getGroupRequest: async (sid, request) => { queries.push([sid, request]); return { ...operation('succeeded'), current: model.current, can_generate: true }; },
    getGroupCandidates: async (_, rid, limit, offset) => ({ current: model.current, can_generate: true, round: { round_id: rid },
      candidates: model.rows, offset, limit, total: 2, has_more: false }),
    getGroupCandidate: async (_, rid, cid) => ({ current: model.current, can_generate: true,
      candidate: model.rows.find(row => row.candidate_id === cid), round: { round_id: rid, selected_candidate_id: model.current.latest?.candidate_id ?? 11 },
      utterances: [{ content: 'saved prefix' }], state_preview: { candidate_id: cid, members: [{ affection_score: 99 }] } }),
    sendGroupRound: submit('send'), regenerateGroupRound: submit('regenerate'), resumeGroupRound: submit('resume'),
    selectGroupCandidate: submit('select'), discardGroupRound: submit('discard'), ...overrides,
  };
  const load = createLoader({ platform, mocks: {
    '@/api/config': { getBaseUrl: () => server, USE_MOCK: mock }, '@/api/groupSessions': api,
  }, globals: { uni: { getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, plain(value)),
    removeStorageSync: key => storage.delete(key) },
    setTimeout: callback => { timers.set(++nextTimer, callback); return nextTimer; }, clearTimeout: key => timers.delete(key),
  } });
  const flow = load('composables/useGroupRoundFlow.ts').useGroupRoundFlow({ id: () => id, active: () => active, generation: resolveGeneration,
    capture: () => { const version = generation, oldId = id, oldServer = server;
      return () => active && generation === version && id === oldId && server === oldServer; }, blocked: () => false });
  return { flow, model, posts, queries, storage, timers, api,
    async start() { await flow.loadRounds(); await flush(); },
    hide() { active = false; generation++; flow.pause(); },
    async show() { active = true; generation++; await flow.loadRounds(); await flush(); },
    target(sid = 2, address = server) { generation++; id = sid; server = address; flow.reset(); },
    async tick() { const callbacks = [...timers.values()]; timers.clear(); for (const callback of callbacks) callback(); await flush(); },
    stop() { active = false; generation++; flow.pause(); },
  };
}

for (const platform of ['H5', 'APP-PLUS', 'MP-WEIXIN']) {
  test(`${platform}: send and regenerate use chosen model parameters while resume keeps frozen parameters`, async () => {
    let resolutions = 0;
    const selected = { model: 'chosen-model', thinking_mode: 'enabled', reasoning_effort: 'high' };
    const f = fixture({}, { platform, generation: async id => { assert.equal(id, 1); resolutions++; return selected; } });
    await f.start(); f.flow.draft.value = 'hello';
    await f.flow.command('send'); await flush();
    assert.equal(f.posts[0].body.model, selected.model);
    assert.equal(f.posts[0].body.thinking_mode, 'enabled');
    assert.equal(f.posts[0].body.reasoning_effort, 'high');
    f.model.current = state(1, latest()); await f.flow.loadRounds();
    await f.flow.command('regenerate'); await flush();
    assert.equal(f.posts[1].body.model, selected.model);
    await f.flow.loadCandidates(1);
    await f.flow.command('resume', f.flow.candidates.value.find(row => row.candidate_id === 12)); await flush();
    assert.equal(resolutions, 2);
    assert.equal(f.posts[2].kind, 'resume');
    assert.equal(f.posts[2].body.model, undefined);
    assert.equal(f.posts[2].body.thinking_mode, undefined);
    f.stop();
  });

  test(`${platform}: waiting for model settings blocks duplicate sends and leaving cancels the pending submission`, async () => {
    const pending = deferred();
    const f = fixture({}, { platform, generation: () => pending.promise });
    await f.start(); f.flow.draft.value = 'kept draft';
    const sending = f.flow.command('send');
    await f.flow.command('send');
    assert.equal(f.flow.submitting.value, true);
    assert.equal(f.posts.length, 0); assert.equal(f.storage.size, 0);
    f.hide(); await f.show();
    pending.resolve({ model: 'late-model', thinking_mode: 'disabled' }); await sending;
    assert.equal(f.posts.length, 0); assert.equal(f.storage.size, 0);
    assert.equal(f.flow.draft.value, 'kept draft');
    f.stop();
  });

  test(`${platform}: submits one frozen command, persists UUID first and reads results with GET`, async () => {
    const post = deferred(); let body;
    const f = fixture({ sendGroupRound: (sid, params) => { body = plain(params); assert.equal(f.storage.size, 1); return post.promise; } }, { platform });
    await f.start(); f.flow.draft.value = '  原话 😀  ';
    const saving = f.flow.command('send'); await f.flow.command('send');
    assert.equal(f.flow.submitting.value, true);
    assert.equal(body.user_content, '  原话 😀  '); assert.equal(body.expected_group_revision, 0);
    assert.match(body.client_request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    f.model.current = state(2, latest());
    post.resolve({ status: 'queued', accepted: { group_revision: 1 } }); await saving; await flush();
    assert.equal(f.queries.length, 1); assert.equal(f.queries[0][1], body.client_request_id);
    assert.equal(f.flow.current.value.group_revision, 2); assert.equal(f.flow.draft.value, '');
    assert.equal(f.storage.size, 0); assert.equal(f.flow.pending.value, null); f.stop();
  });
}

test('model resolution failure preserves the draft and creates no request receipt', async () => {
  const f = fixture({}, { generation: async () => { throw new Error('settings unavailable'); } });
  await f.start(); f.flow.draft.value = 'kept';
  await f.flow.command('send');
  assert.equal(f.posts.length, 0); assert.equal(f.storage.size, 0);
  assert.equal(f.flow.draft.value, 'kept');
  assert.match(f.flow.operationError.value, /模型配置/);
  assert.equal(f.flow.submitting.value, false);
  f.stop();
});

test('unknown POST and 404 never send again; manual GET restores the accepted result and clears its draft', async () => {
  let posts = 0, accepted = false;
  const f = fixture({ sendGroupRound: async () => { posts++; throw new Error('timeout'); },
    getGroupRequest: async () => { if (!accepted) throw new Error('[API Error 404] /requests: {"detail":"not yet"}');
      return { ...operation('succeeded'), current: state(2, latest()), can_generate: true }; } });
  await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  assert.equal(f.flow.pending.value.kind, 'send'); assert.match(f.flow.operationError.value, /结果待确认/);
  assert.equal(f.flow.locked.value, true); assert.equal(f.timers.size, 0);
  await f.flow.command('send'); await f.tick(); assert.equal(posts, 1);
  accepted = true; f.model.current = state(2, latest()); await f.flow.recover();
  assert.equal(posts, 1); assert.equal(f.flow.pending.value, null); assert.equal(f.flow.draft.value, ''); f.stop();
});

test('running work polls only GET; a query error stops timers and preserves recovery information', async () => {
  let fails = false, queries = 0;
  const f = fixture({ getGroupRequest: async () => { queries++; if (fails) throw new Error('offline');
    return { ...operation(), current: state(1, latest(), operation()), can_generate: true }; } });
  await f.start(); f.flow.draft.value = 'hello'; const saving = f.flow.command('send');
  f.model.current = state(1, latest(), operation()); await saving; await flush();
  assert.equal(f.timers.size, 1); fails = true; await f.tick();
  assert.equal(queries, 2); assert.equal(f.posts.length, 1); assert.equal(f.timers.size, 0);
  assert.equal(f.storage.size, 1); assert.equal(f.flow.locked.value, true); f.stop();
});

test('terminal result keeps writes locked until history refresh succeeds', async () => {
  let fails = false;
  const f = fixture({ getGroupRounds: async () => { if (fails) throw new Error('read failed'); return page(f.model.current); } });
  await f.start(); fails = true; f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  assert.equal(f.flow.locked.value, true); assert.equal(f.storage.size, 1);
  fails = false; await f.flow.recover(); assert.equal(f.flow.pending.value, null); f.stop();
});

test('page recreation restores a server-scoped UUID without any POST', async () => {
  const storage = new Map([['group_request:https%3A%2F%2Fa.invalid:1', { request_id: uuid, kind: 'send' }]]);
  const f = fixture({}, { storage }); await f.start();
  assert.deepEqual(f.queries, [[1, uuid]]); assert.equal(f.posts.length, 0); assert.equal(storage.size, 0); f.stop();
});

test('existing server task is discovered when no local request remains', async () => {
  const f = fixture(); f.model.current = state(1, latest(), operation()); await f.start();
  assert.equal(f.queries[0][1], uuid); assert.equal(f.flow.operationBusy.value, true); f.stop();
});

for (const change of ['hide', 'session', 'server-aba']) {
  test(`late POST cannot overwrite state after ${change}; return recovers with GET`, async () => {
    const post = deferred();
    const f = fixture({ sendGroupRound: () => post.promise }); await f.start(); f.flow.draft.value = 'hello';
    const sending = f.flow.command('send');
    if (change === 'hide') { f.hide(); await f.show(); }
    else { f.target(2, 'https://b.invalid'); await f.start(); if (change === 'server-aba') { f.target(1, 'https://a.invalid'); await f.start(); } }
    post.resolve({ status: 'queued', accepted: { group_revision: 999 } }); await sending; await flush();
    assert.equal(f.flow.current.value.group_revision, 0); assert.equal(f.flow.submitting.value, false);
    assert.equal(f.flow.notice.value.includes('请求已接受'), false);
    assert.equal(f.queries.length, change === 'session' ? 0 : 1); f.stop();
  });
}

test('late GET and candidate preview cannot repopulate a different target', async () => {
  const result = deferred(), preview = deferred();
  const f = fixture({ getGroupRequest: () => result.promise, getGroupCandidate: () => preview.promise });
  await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  await f.flow.loadCandidates(1); const reading = f.flow.viewCandidate(1, 11); f.target(); await f.start();
  result.resolve({ ...operation('succeeded'), current: state(99, latest()), can_generate: true });
  preview.resolve({ current: state(99, latest()), candidate: candidate(11), can_generate: true });
  await reading; await flush(); assert.equal(f.flow.current.value.group_revision, 0);
  assert.equal(f.flow.preview.value, null); assert.equal(f.flow.pending.value, null); f.stop();
});

test('candidate preview is separate from adopted selection; select and resume use fresh target revisions', async () => {
  const f = fixture(); f.model.current = state(8, latest()); await f.start();
  await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 12);
  assert.equal(f.flow.current.value.latest.candidate_id, 11); assert.equal(f.flow.preview.value.state_preview.candidate_id, 12);
  await f.flow.command('select', f.flow.candidates.value[1]); assert.equal(f.posts.length, 0);
  await f.flow.command('resume', f.flow.candidates.value[1], async () => true); await flush();
  assert.equal(f.posts[0].kind, 'resume'); assert.equal(f.posts[0].body.target_candidate_id, 12);
  assert.equal(f.posts[0].body.target_candidate_revision, 4); assert.equal(f.posts[0].body.expected_group_revision, 8);
  assert.equal(f.posts[0].body.observed_candidate_id, 11); assert.equal('model' in f.posts[0].body, false); f.stop();
});

test('regenerate, select and discard preserve action identity without consuming draft', async () => {
  const f = fixture(); f.model.current = state(8, latest()); f.model.rows[1] = candidate(12, 'awaiting_confirmation', false);
  await f.start(); f.flow.draft.value = 'next draft'; await f.flow.loadCandidates(1);
  await f.flow.command('select', f.flow.candidates.value[1]); await flush();
  await f.flow.command('regenerate'); await flush();
  await f.flow.command('discard', undefined, async () => true); await flush();
  assert.deepEqual(f.posts.map(row => row.kind), ['select', 'regenerate', 'discard']);
  assert.equal(f.flow.draft.value, 'next draft'); assert.equal(new Set(f.posts.map(row => row.body.client_request_id)).size, 3); f.stop();
});

test('stale confirmation cannot dispatch and a declined confirmation leaves no pending record', async () => {
  const confirmation = deferred(); const f = fixture(); f.model.current = state(8, latest()); await f.start();
  await f.flow.command('discard', undefined, async () => false); assert.equal(f.storage.size, 0);
  const asking = f.flow.command('discard', undefined, () => confirmation.promise); f.target();
  confirmation.resolve(true); await asking; assert.equal(f.posts.length, 0); assert.equal(f.storage.size, 0); f.stop();
});

test('known validation rejection preserves draft, consumes no recovery record and refreshes observation', async () => {
  const f = fixture({ sendGroupRound: async () => { throw new Error('[API Error 422] /rounds: {"detail":"bad model"}'); } });
  await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  assert.equal(f.flow.draft.value, 'hello'); assert.equal(f.storage.size, 0); assert.equal(f.queries.length, 0);
  assert.match(f.flow.operationError.value, /bad model/); assert.equal(f.flow.canSend.value, true); f.stop();
});

test('storage failure blocks POST before dispatch', async () => {
  const storage = new Map(); storage.set = () => { throw new Error('quota exceeded'); };
  const f = fixture({}, { storage }); await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send');
  assert.equal(f.posts.length, 0); assert.match(f.flow.operationError.value, /本次未发送/); f.stop();
});

test('older GET snapshots and candidate revisions cannot roll current state backwards', async () => {
  const old = deferred(); const f = fixture({ getGroupCandidate: () => old.promise });
  f.model.current = state(8, latest(11, 5)); await f.start(); await f.flow.loadCandidates(1);
  const reading = f.flow.viewCandidate(1, 11);
  f.model.current = state(9, latest(12, 8)); await f.flow.loadCandidates(1);
  old.resolve({ current: state(8, latest(11, 5)), can_generate: true, candidate: candidate(11) }); await reading;
  assert.equal(f.flow.current.value.latest.candidate_id, 12); assert.equal(f.flow.preview.value, null);
  f.model.current = state(9, latest(12, 6)); await f.flow.loadRounds();
  assert.equal(f.flow.current.value.latest.candidate_revision, 8); f.stop();
});

test('legacy and offline pages stay readable without exposing generation', async () => {
  for (const mock of [false, true]) {
    const f = fixture({ getGroupRounds: async () => ({ rounds: [round()], offset: 0, has_more: false }) }, { mock });
    await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send');
    assert.equal(f.flow.rounds.value.length, 1); assert.equal(f.flow.canSend.value, false); assert.equal(f.posts.length, 0); f.stop();
  }
});

test('hiding cancels polling and clears candidate views; return checks the same request before unlocking', async () => {
  let done = false;
  const f = fixture({ getGroupRequest: async () => ({ ...operation(done ? 'succeeded' : 'running'),
    current: f.model.current, can_generate: true }) });
  await f.start(); f.flow.draft.value = 'hello'; const saving = f.flow.command('send');
  f.model.current = state(1, latest(), operation()); await saving; await flush();
  await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 11);
  f.hide(); assert.equal(f.timers.size, 0); assert.equal(f.flow.preview.value, null);
  assert.equal(f.flow.current.value, null); assert.equal(f.flow.pending.value.kind, 'send');
  done = true; f.model.current = state(2, latest()); await f.show();
  assert.equal(f.flow.pending.value, null); assert.equal(f.posts.length, 1); f.stop();
});

test('resume confirmation freezes the target and retains a newer draft on completion', async () => {
  const confirmation = deferred(); const f = fixture(); f.model.current = state(8, latest()); await f.start();
  await f.flow.loadCandidates(1); const target = f.flow.candidates.value[1]; f.flow.draft.value = 'next draft';
  const asking = f.flow.command('resume', target, () => confirmation.promise);
  target.revision = 999; confirmation.resolve(true); await asking; await flush();
  assert.equal(f.posts[0].body.target_candidate_revision, 4); assert.equal(f.flow.draft.value, 'next draft'); f.stop();
});

test('failed or unavailable selected candidates cannot confirm a new user message', async () => {
  const f = fixture(); f.model.current = state(8, latest()); f.model.current.capabilities.can_send = false;
  await f.start(); f.flow.draft.value = 'next'; await f.flow.command('send');
  assert.equal(f.posts.length, 0); assert.equal(f.flow.canRegenerate.value, true);
  f.model.current.capabilities.can_send = true;
  f.api.getGroupRounds = async () => ({ ...page(f.model.current), can_generate: false }); await f.flow.loadRounds();
  await f.flow.command('send'); await f.flow.command('regenerate'); assert.equal(f.posts.length, 0);
  assert.equal(f.flow.canDiscard.value, true); f.stop();
});

test('candidate pagination keeps the last page on failure and retries its offset', async () => {
  const offsets = []; let fails = true;
  const f = fixture({ getGroupCandidates: async (_, rid, limit, offset) => {
    offsets.push(offset); if (offset && fails) { fails = false; throw new Error('offline'); }
    return { current: f.model.current, can_generate: true, candidates: [candidate(offset ? 11 : 12)],
      offset, has_more: !offset, total: 2 };
  } });
  f.model.current = state(8, latest()); await f.start(); await f.flow.loadCandidates(1);
  await f.flow.loadCandidates(1, true); assert.equal(f.flow.candidates.value.length, 1);
  assert.match(f.flow.candidatesError.value, /offline/); await f.flow.loadCandidates(1, true);
  assert.deepEqual(offsets, [0, 1, 1]); assert.equal(f.flow.candidates.value.length, 2); f.stop();
});

test('switching candidate rounds rejects late previews and an old recovery refresh cannot open another round', async () => {
  const delayed = deferred(); let reads = 0;
  const f = fixture({ getGroupCandidate: () => { reads++; return delayed.promise; } });
  f.model.current = state(8, latest()); await f.start(); await f.flow.loadCandidates(1);
  const reading = f.flow.viewCandidate(1, 11); await f.flow.loadCandidates(2);
  delayed.resolve({ current: f.model.current, can_generate: true, candidate: candidate(11), round: { round_id: 1 } });
  await reading; await f.flow.viewCandidate(1, 11);
  assert.equal(f.flow.candidateRoundId.value, 2); assert.equal(f.flow.preview.value, null); assert.equal(reads, 1); f.stop();
});

test('a paused recovery cannot start a new preview on the next session with the same round ID', async () => {
  const delayed = deferred(); let hold = false, previewReads = 0;
  const f = fixture();
  const readCandidates = f.api.getGroupCandidates, readPreview = f.api.getGroupCandidate;
  f.api.getGroupCandidates = (...args) => hold ? delayed.promise : readCandidates(...args);
  f.api.getGroupCandidate = (...args) => { previewReads++; return readPreview(...args); };
  f.model.current = state(8, latest()); await f.start(); await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 11);
  hold = true; f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  assert.equal(f.flow.recovering.value, true);
  f.target(2); hold = false; await f.start(); await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 12);
  const before = previewReads;
  delayed.resolve({ current: state(8, latest()), can_generate: true, candidates: [], offset: 0, has_more: false }); await flush();
  assert.equal(previewReads, before); assert.equal(f.flow.preview.value.candidate.candidate_id, 12); f.stop();
});

test('recovery refresh does not replace a preview explicitly chosen while candidate metadata is pending', async () => {
  const delayed = deferred(); let hold = false;
  const f = fixture(); const readCandidates = f.api.getGroupCandidates;
  f.api.getGroupCandidates = (...args) => hold ? delayed.promise : readCandidates(...args);
  f.model.current = state(8, latest()); await f.start(); await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 11);
  hold = true; f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  await f.flow.viewCandidate(1, 12);
  delayed.resolve({ current: state(8, latest()), can_generate: true, candidates: f.model.rows, offset: 0, has_more: false }); await flush();
  assert.equal(f.flow.preview.value.candidate.candidate_id, 12); f.stop();
});

test('candidate queries cannot confirm a newer adopted candidate until the main history is refreshed', async () => {
  const f = fixture(); f.model.current = state(8, latest()); await f.start();
  f.model.current = state(9, latest(12)); await f.flow.loadCandidates(1);
  assert.equal(f.flow.rounds.value[0].candidate_id, 11); f.flow.draft.value = 'next';
  await f.flow.command('send'); assert.equal(f.posts.length, 0);
  await f.flow.loadRounds(); assert.equal(f.flow.rounds.value[0].candidate_id, 12);
  assert.equal(f.flow.canSend.value, true); f.stop();
});

test('pagination metadata cannot stand in for seeing the latest adopted content', async () => {
  const f = fixture(); f.model.current = state(8, latest()); await f.start();
  f.flow.hasMoreRounds.value = true; f.model.current = state(9, latest(12));
  f.api.getGroupRounds = async () => ({ ...page(f.model.current), rounds: [round(10)], offset: 1 });
  await f.flow.loadRounds(true); assert.equal(f.flow.rounds.value[0].candidate_id, 11);
  assert.equal(f.flow.canSend.value, false); f.stop();
});

test('a definite rejection with a failed storage cleanup stays recoverable without querying an unaccepted UUID', async () => {
  const storage = new Map(); const remove = storage.delete.bind(storage); let fails = true;
  storage.delete = key => { if (fails) throw new Error('storage unavailable'); return remove(key); };
  const f = fixture({ sendGroupRound: async () => { throw new Error('[API Error 422] /rounds: {"detail":"invalid"}'); } }, { storage });
  await f.start(); f.flow.draft.value = 'hello'; await f.flow.command('send'); await flush();
  assert.match(f.flow.operationError.value, /本机|存储/); assert.equal(f.flow.pending.value.kind, 'send');
  fails = false; await f.flow.recover();
  assert.equal(f.queries.length, 0); assert.equal(f.flow.pending.value, null); assert.equal(f.flow.draft.value, 'hello'); f.stop();
});

test('a persisted definite rejection can be cleaned after recreating the page without a request GET', async () => {
  const storage = new Map([['group_request:https%3A%2F%2Fa.invalid:1', { request_id: uuid, kind: 'send', rejected: true }]]);
  const f = fixture({}, { storage }); await f.start();
  assert.equal(f.queries.length, 0); assert.equal(f.flow.pending.value, null); assert.equal(storage.size, 0); f.stop();
});

test('an active task discovered through candidates can be queried without a local receipt', async () => {
  const f = fixture(); await f.start(); f.model.current = state(1, latest(), operation());
  await f.flow.loadCandidates(1); assert.equal(f.flow.pending.value, null);
  await f.flow.recover(); assert.equal(f.queries[0][1], uuid);
  assert.equal(f.posts.length, 0); f.stop();
});

for (const platform of ['H5', 'APP-PLUS', 'MP-WEIXIN']) {
  test(`${platform}: adopted state uses selected candidate and stays separate from another preview`, async () => {
    const f = fixture({}, { platform }); f.model.current = state(8, latest()); await f.start();
    await f.flow.loadAdoptedState();
    assert.equal(f.flow.adoptedState.value.candidate.candidate_id, 11);
    await f.flow.loadCandidates(1); await f.flow.viewCandidate(1, 12);
    assert.equal(f.flow.preview.value.candidate.candidate_id, 12);
    assert.equal(f.flow.adoptedState.value.candidate.candidate_id, 11);
    assert.equal(f.posts.length, 0); f.stop();
  });
}

test('adopted state invalidates immediately when selected candidate or confirmation changes', async () => {
  const f = fixture(); f.model.current = state(8, latest()); await f.start(); await f.flow.loadAdoptedState();
  f.model.current = state(9, latest(12)); await f.flow.loadRounds();
  assert.equal(f.flow.adoptedState.value, null);
  await f.flow.loadAdoptedState(); assert.equal(f.flow.adoptedState.value.candidate.candidate_id, 12);
  f.model.current = state(10, { ...latest(12), confirmed: true }); await f.flow.loadRounds();
  assert.equal(f.flow.adoptedState.value, null); f.stop();
});

test('late adopted reads cannot overwrite a new story or A to B to A server context', async () => {
  const old = deferred(); const f = fixture({ getGroupCandidate: () => old.promise });
  f.model.current = state(8, latest()); await f.start(); const reading = f.flow.loadAdoptedState();
  f.target(2, 'https://b.invalid'); f.target(1, 'https://a.invalid'); await f.start();
  old.resolve({ current: state(8, latest()), candidate: candidate(11),
    round: { round_id: 1, selected_candidate_id: 11 }, state_preview: { candidate_id: 11, members: [] } });
  await reading; assert.equal(f.flow.adoptedState.value, null); assert.equal(f.flow.loadingAdoptedState.value, false); f.stop();
});

test('adopted state read errors are retryable and mismatched versions are not displayed', async () => {
  let broken = true;
  const f = fixture({ getGroupCandidate: async () => {
    if (broken) throw new Error('offline');
    return { current: state(8, latest()), candidate: candidate(11), round: { round_id: 1, selected_candidate_id: 11 },
      state_preview: { candidate_id: 11, members: [] } };
  } });
  f.model.current = state(8, latest()); await f.start(); await f.flow.loadAdoptedState();
  assert.match(f.flow.adoptedStateError.value, /offline/); assert.equal(f.flow.loadingAdoptedState.value, false);
  broken = false; await f.flow.loadAdoptedState(); assert.equal(f.flow.adoptedState.value.candidate.candidate_id, 11);
  f.model.current = state(9, latest(11, 5)); await f.flow.loadRounds(); await f.flow.loadAdoptedState();
  assert.equal(f.flow.adoptedState.value, null); assert.match(f.flow.adoptedStateError.value, /刷新/); f.stop();
});

test('a late state read cannot replace a newer selected candidate state', async () => {
  const old = deferred(); let reads = 0;
  const f = fixture({ getGroupCandidate: async () => ++reads === 1 ? old.promise : ({
    current: state(9, latest(12)), candidate: candidate(12), round: { round_id: 1, selected_candidate_id: 12 },
    state_preview: { candidate_id: 12, members: [] },
  }) });
  f.model.current = state(8, latest()); await f.start(); const reading = f.flow.loadAdoptedState();
  f.model.current = state(9, latest(12)); await f.flow.loadRounds(); await f.flow.loadAdoptedState();
  old.resolve({ current: state(8, latest()), candidate: candidate(11), round: { round_id: 1, selected_candidate_id: 11 },
    state_preview: { candidate_id: 11, members: [] } });
  await reading; assert.equal(f.flow.adoptedState.value.candidate.candidate_id, 12); f.stop();
});

test('hiding or submitting invalidates adopted state without replaying a POST', async () => {
  const f = fixture(); f.model.current = state(8, latest()); await f.start(); await f.flow.loadAdoptedState();
  f.hide(); assert.equal(f.flow.adoptedState.value, null);
  await f.show(); await f.flow.loadAdoptedState();
  await f.flow.command('discard'); assert.equal(f.flow.adoptedState.value, null);
  assert.equal(f.posts.length, 1); f.stop();
});
