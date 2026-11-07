const test = require('node:test');
const assert = require('node:assert/strict');
const { ref } = require('vue');
const { createLoader, deferred } = require('./helpers/load-ts.cjs');

const current = (revision = 1, candidate = 11) => ({ group_revision: revision,
  latest: { round_id: 1, candidate_id: candidate, candidate_revision: revision, confirmed: false },
  active_operation: null, capabilities: { can_send: true } });
const projection = state => ({ session_id: 1, current: state, can_update: true,
  members: [{ persona_id: 7, portrait_id: null, image_path: 'avatar.png' }] });

function fixture(overrides = {}) {
  let id = 1, active = true, generation = 0;
  const state = ref(current()), blocked = ref(false), serverState = ref(current());
  const puts = [], reads = [];
  const api = { getGroupPortraits: async () => projection(serverState.value),
    setGroupPortrait: async (...args) => { puts.push(args); serverState.value = current(2); }, ...overrides };
  const load = createLoader({ mocks: { '@/api/groupSessions': api,
    '@/api/portraits': { getPortraits: overrides.getPortraits || (async (cid, offset) => {
      reads.push([cid, offset]); return { portraits: [{ id: offset + 100, name: 'portrait', image_path: 'p.png' }], has_more: offset === 0 };
    }) } } });
  const flow = load('composables/useGroupPortraits.ts').useGroupPortraits({
    id: () => id, active: () => active, blocked: () => blocked.value, current: () => state.value,
    members: () => [{ persona_id: 7, character: { id: 3 } }, { persona_id: 8, character: { id: 4 } }],
    capture: () => { const version = generation; return () => version === generation && active; },
    invalidate: () => { state.value = null; }, refresh: overrides.refresh || (async () => { state.value = serverState.value; return true; }),
  });
  return { flow, state, blocked, serverState, puts, reads,
    hide() { active = false; generation++; flow.pausePortraits(); },
    target(next = 1) { id = next; generation++; flow.pausePortraits(); state.value = current(); active = true; },
  };
}

test('selection freezes observed versions, sends once and reloads with GET', async () => {
  const waiting = deferred(); let calls = 0, body;
  const f = fixture({ setGroupPortrait: async (sid, pid, params) => {
    calls++; body = JSON.parse(JSON.stringify(params)); assert.equal(sid, 1); assert.equal(pid, 7); await waiting.promise;
  } });
  await f.flow.loadPortraits(); const changing = f.flow.choosePortrait(7, 100);
  await f.flow.choosePortrait(7, 101);
  assert.equal(calls, 1); assert.equal(f.flow.portraitWriting.value, true); assert.equal(f.state.value, null);
  assert.deepEqual(body, { portrait_id: 100, expected_group_revision: 1, observed_round_id: 1,
    observed_candidate_id: 11, observed_candidate_revision: 1 });
  waiting.resolve(); await changing;
  assert.equal(f.flow.portraitWriting.value, false); assert.equal(f.flow.portraitData.value.session_id, 1);
});

test('uncertain selection never retries PUT and a failed refresh leaves no usable choice', async () => {
  let calls = 0;
  const f = fixture({ setGroupPortrait: async () => { calls++; throw new Error('timeout'); }, refresh: async () => false });
  await f.flow.loadPortraits(); await f.flow.choosePortrait(7, null);
  assert.equal(calls, 1); assert.equal(f.flow.portraitData.value, null);
  assert.equal(f.flow.canChoosePortrait.value, false); assert.match(f.flow.portraitError.value, /不会自动重发/);
});

test('candidate changes reject an older portrait read and clear selected images', async () => {
  const old = deferred(); const f = fixture({ getGroupPortraits: () => old.promise });
  const reading = f.flow.loadPortraits(); f.state.value = current(2, 12);
  old.resolve(projection(current())); await reading;
  assert.equal(f.flow.portraitData.value, null); assert.equal(f.flow.loadingPortraits.value, false);
});

test('late writes after hide or server A to B to A cannot unlock a newer context', async () => {
  const old = deferred(), next = deferred(); let writes = 0;
  const f = fixture({ setGroupPortrait: () => ++writes === 1 ? old.promise : next.promise });
  await f.flow.loadPortraits(); const first = f.flow.choosePortrait(7, 100);
  f.hide(); f.target(2); f.target(1); await f.flow.loadPortraits();
  const second = f.flow.choosePortrait(7, 101); old.resolve(); await first;
  assert.equal(f.flow.portraitWriting.value, true);
  next.resolve(); await second; assert.equal(f.flow.portraitWriting.value, false);
});

test('portrait option pagination preserves pages and isolates late results by member', async () => {
  const waiting = deferred(); let calls = 0;
  const f = fixture({ getPortraits: async (cid, offset) => {
    calls++;
    if (cid === 4) return waiting.promise;
    if (calls === 2) throw new Error('network');
    return { portraits: [{ id: offset + 1 }], has_more: offset === 0 };
  } });
  await f.flow.loadPortraits(); await f.flow.loadPortraitOptions(7);
  await f.flow.loadPortraitOptions(7, true); assert.match(f.flow.portraitOptions.value[7].error, /失败/);
  assert.equal(f.flow.portraitOptions.value[7].rows.length, 1);
  await f.flow.loadPortraitOptions(7, true); assert.equal(f.flow.portraitOptions.value[7].rows.length, 2);
  const reading = f.flow.loadPortraitOptions(8); f.target(); waiting.resolve({ portraits: [{ id: 99 }], has_more: false }); await reading;
  assert.deepEqual(Object.keys(f.flow.portraitOptions.value), []);
});

test('busy operations, mismatched snapshots and unsupported servers cannot enable choices', async () => {
  const f = fixture(); await f.flow.loadPortraits(); f.blocked.value = true;
  await f.flow.choosePortrait(7, 1); assert.equal(f.puts.length, 0);
  f.blocked.value = false; f.serverState.value = current(3); await f.flow.loadPortraits();
  assert.equal(f.flow.portraitData.value, null); assert.match(f.flow.portraitError.value, /更新/);
  const legacy = fixture({ getGroupPortraits: async () => { throw new Error('404'); } });
  await legacy.flow.loadPortraits(); assert.equal(legacy.flow.canChoosePortrait.value, false);
  assert.match(legacy.flow.portraitError.value, /旧服务器|离线/);
});
