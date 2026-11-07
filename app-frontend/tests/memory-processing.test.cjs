const assert = require("node:assert/strict");
const test = require("node:test");
const { effectScope, ref, nextTick } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

const status = (extra = {}) => ({ session_id: 1, status: "completed", pending_count: 0,
  processing_count: 0, error_codes: [], last_completed_at: null, ...extra });
const settle = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); };

function fixture(api = {}) {
  const id = ref(1), timers = new Map(), reads = [], posts = [];
  let server = "https://one.test", changed, clock = 0, completions = 0;
  const scope = effectScope();
  const load = createLoader({ mocks: {
    "@/api/config": { getBaseUrl: () => server, USE_MOCK: false },
    "@/utils/connectionEvents": { onServerChange: fn => { changed = fn; return () => { changed = null; }; } },
    "@/api/memories": {
      getMemoryProcessingStatus: async (...args) => { reads.push(args); return api.get ? api.get(...args) : status(); },
      triggerSummary: async (...args) => { posts.push(args); return api.post ? api.post(...args) : status({ status: "pending", pending_count: 1 }); },
    },
  }, globals: {
    setTimeout: fn => { timers.set(++clock, fn); return clock; },
    clearTimeout: key => timers.delete(key),
  } });
  const state = scope.run(() => load("composables/useMemoryProcessing.ts").useMemoryProcessing(() => id.value, () => completions++));
  return { state, id, timers, reads, posts, scope, completions: () => completions,
    server(value) { server = value; changed?.(); },
    async tick() { const [key, fn] = timers.entries().next().value; timers.delete(key); fn(); await settle(); },
  };
}

test("polls with GET only, reports completion once and stops timers on close", async () => {
  let n = 0;
  const f = fixture({ get: () => ++n === 1 ? status({ status: "pending", pending_count: 1 }) :
    status({ last_completed_at: "2026-10-28T01:02:03Z" }) });
  await settle();
  assert.equal(f.state.busy.value, true);
  await f.state.extract();
  assert.equal(f.posts.length, 0);
  await f.tick();
  assert.equal(f.state.busy.value, false);
  assert.equal(f.completions(), 1);
  await f.tick();
  assert.equal(f.completions(), 1);
  assert.equal(f.posts.length, 0);
  f.scope.stop();
  assert.equal(f.timers.size, 0);
});

test("double tap posts once and an uncertain result is queried without reposting", async () => {
  const pending = deferred();
  const f = fixture({ post: () => pending.promise });
  await settle();
  const action = f.state.extract();
  await f.state.extract();
  assert.equal(f.posts.length, 1);
  pending.reject(new Error("network lost after server accepted"));
  await action;
  assert.match(f.state.error.value, /未确认/);
  await f.state.extract();
  assert.equal(f.posts.length, 1);
  await f.tick();
  assert.equal(f.state.error.value, "");
  assert.equal(f.posts.length, 1);
  f.scope.stop();
});

test("a read failure keeps the known queue and cannot announce completion", async () => {
  let fails = false;
  const f = fixture({ get: () => {
    if (fails) throw new Error("offline");
    return status({ status: "retrying", pending_count: 2, error_codes: ["extraction_failed"] });
  } });
  await settle();
  fails = true;
  await f.tick();
  assert.equal(f.state.state.value.pending_count, 2);
  assert.match(f.state.error.value, /无法查询/);
  assert.equal(f.completions(), 0);
  f.scope.stop();
});

test("switching stories ignores a late GET and reads only the new story", async () => {
  const old = deferred();
  const f = fixture({ get: id => id === 1 ? old.promise : status({ session_id: id }) });
  f.id.value = 2;
  await settle();
  old.resolve(status({ status: "retrying", pending_count: 99 }));
  await settle();
  assert.equal(f.state.state.value.session_id, 2);
  assert.equal(f.state.state.value.pending_count, 0);
  assert.equal(f.completions(), 0);
  f.scope.stop();
});

test("server round trips invalidate old POST failures and dispose releases the subscription", async () => {
  const old = deferred();
  const f = fixture({ post: () => old.promise });
  await settle();
  const action = f.state.extract();
  f.server("https://two.test");
  f.server("https://one.test");
  await settle();
  old.reject(new Error("old failure"));
  await action;
  assert.equal(f.state.error.value, "");
  assert.equal(f.state.submitting.value, false);
  f.scope.stop();
  const reads = f.reads.length;
  f.server("https://three.test");
  assert.equal(f.reads.length, reads);
  assert.equal(f.timers.size, 0);
});

test("closing during a POST ignores its late success and never starts another timer", async () => {
  const old = deferred();
  const f = fixture({ post: () => old.promise });
  await settle();
  const action = f.state.extract();
  f.scope.stop();
  old.resolve(status({ status: "pending", pending_count: 1 }));
  await action;
  assert.equal(f.state.state.value.pending_count, 0);
  assert.equal(f.timers.size, 0);
  assert.equal(f.completions(), 0);
});

test("progress API uses the shared authenticated GET and mock never invents completion times", async () => {
  const calls = [];
  const load = createLoader({ mocks: { "../config": {}, "./sessions": {}, "./config": { USE_MOCK: false,
    request: async (...args) => { calls.push(args); return status(); } } } });
  await load("api/memories.ts").getMemoryProcessingStatus(7);
  assert.equal(calls[0][0], "/sessions/7/memory-processing");
  assert.equal(calls[0][1].method, "GET");
  const mock = createLoader({ mocks: { "../config": {}, "./sessions": {}, "./config": { USE_MOCK: true } } })("api/memories.ts");
  const result = await mock.getMemoryProcessingStatus(7);
  assert.equal(result.last_completed_at, null);
  assert.equal(result.pending_count, 0);
});
