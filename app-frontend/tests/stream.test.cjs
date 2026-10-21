const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");

const params = { session_id: 1, user_message: "你好" };
const wire = 'data: {"reasoning_chunk":"想🙂"}\r\n\r\ndata:{"chunk":"你好🙂"}\n\ndata: {"assistant_message_id":2,"affection_score":3}\n\n';
function capture() {
  const result = { chunks: [], reasoning: [], done: [], errors: [] };
  return { result, callbacks: {
    chunk: (v) => result.chunks.push(v), reasoning: (v) => result.reasoning.push(v),
    done: (v) => result.done.push(v), error: (e) => result.errors.push(e),
  } };
}

for (const native of [true, false]) {
  test(`UTF-8 preserves Chinese and emoji at every byte boundary (native=${native})`, () => {
    const load = createLoader({ globals: native ? {} : { TextDecoder: undefined } });
    const { createUtf8Decoder } = load("utils/sse.ts");
    const expected = "中文🙂尾";
    const bytes = new TextEncoder().encode(expected);
    for (let split = 0; split <= bytes.length; split++) {
      const decoder = createUtf8Decoder();
      assert.equal(decoder.push(bytes.slice(0, split)) + decoder.push(bytes.slice(split)) + decoder.finish(), expected);
    }
  });
}

test("SSE handles split CRLF, comments, multiline data and a final unterminated frame", () => {
  const { createSSEParser } = createLoader()("utils/sse.ts");
  const text = ': heartbeat\r\ndata: first\r\ndata:second\r\n\r\ndata: last';
  for (let split = 0; split <= text.length; split++) {
    const frames = [];
    const parser = createSSEParser((frame) => frames.push(frame));
    parser.push(text.slice(0, split)); parser.push(text.slice(split)); parser.finish();
    assert.deepEqual(frames, ["first\nsecond", "last"]);
  }
});

test("H5 receives one-byte chunks without corrupting text or final metadata", async () => {
  const bytes = new TextEncoder().encode(wire);
  let index = 0, released = false;
  const reader = {
    read: async () => index < bytes.length ? { done: false, value: bytes.slice(index, ++index) } : { done: true },
    cancel: async () => {}, releaseLock: () => { released = true; },
  };
  const load = createLoader({ globals: { fetch: async () => ({ ok: true, body: { getReader: () => reader } }) } });
  const { receiveChatStream } = load("api/chatStream.ts");
  const { result, callbacks } = capture();
  await receiveChatStream("/chat/stream", {}, params, callbacks);
  assert.deepEqual(result.chunks, ["你好🙂"]);
  assert.deepEqual(result.reasoning, ["想🙂"]);
  assert.equal(result.done.length, 1);
  assert.equal(result.done[0].assistant_message_id, 2);
  assert.equal(result.errors.length, 0);
  assert.equal(released, true);
});

for (const [name, body] of [
  ["server error", 'data: {"error":"模型失败"}\n\n'],
  ["truncated reply", 'data: {"chunk":"未完成"}\n\n'],
  ["invalid JSON", 'data: {broken}\n\n'],
]) {
  test(`H5 reports ${name} exactly once, without a false successful completion`, async () => {
    const load = createLoader({ globals: { fetch: async () => ({ ok: true, text: async () => body }) } });
    const { result, callbacks } = capture();
    await load("api/chatStream.ts").receiveChatStream("/chat/stream", {}, params, callbacks);
    assert.equal(result.errors.length, 1);
    assert.equal(result.done.length, 0);
  });
}

test("H5 cancellation aborts an in-flight request without surfacing a network error", async () => {
  const started = deferred();
  const load = createLoader({ globals: { fetch: (_, options) => new Promise((_, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    started.resolve(options.signal);
  }) } });
  const cancellation = load("utils/cancellation.ts").createCancellation();
  const { result, callbacks } = capture();
  const request = load("api/chatStream.ts").receiveChatStream("/chat/stream", {}, params, callbacks, cancellation);
  const signal = await started.promise;
  cancellation.cancel();
  await request;
  assert.equal(signal.aborted, true);
  assert.equal(result.errors.length, 0);
  assert.equal(result.done.length, 0);
});

for (const chunked of [true, false]) {
  test(`mini-program consumes SSE using a single uni.request (chunked=${chunked})`, async () => {
    let count = 0, onChunk;
    const load = createLoader({ platform: "MP-WEIXIN", globals: {
      TextDecoder: undefined,
      fetch: () => { throw new Error("Browser fetch must not run"); },
      uni: { request(options) {
        count++;
        queueMicrotask(() => {
          if (chunked) for (const byte of new TextEncoder().encode(wire)) onChunk({ data: new Uint8Array([byte]).buffer });
          options.success({ statusCode: 200, data: wire });
        });
        return { abort() {}, ...(chunked ? { onChunkReceived(callback) { onChunk = callback; } } : {}) };
      } },
    } });
    const { result, callbacks } = capture();
    await load("api/chatStream.ts").receiveChatStream("/chat/stream", {}, params, callbacks);
    assert.equal(count, 1);
    assert.deepEqual(result.chunks, ["你好🙂"]);
    assert.equal(result.done.length, 1);
    assert.equal(result.errors.length, 0);
  });
}

test("mini-program cancellation aborts its task and ignores the abort failure callback", async () => {
  let aborted = false;
  const load = createLoader({ platform: "MP-WEIXIN", globals: { uni: { request(options) {
    return { abort() { aborted = true; options.fail({ errMsg: "abort" }); } };
  } } } });
  const cancellation = load("utils/cancellation.ts").createCancellation();
  const { result, callbacks } = capture();
  const request = load("api/chatStream.ts").receiveChatStream("/chat/stream", {}, params, callbacks, cancellation);
  cancellation.cancel(); await request;
  assert.equal(aborted, true);
  assert.equal(result.errors.length, 0);
});

test("a failed mini-program stream is never replayed as a second chat POST", async () => {
  let count = 0;
  const load = createLoader({ platform: "MP-WEIXIN", globals: { uni: { request(options) {
    count++;
    queueMicrotask(() => options.fail({ errMsg: "offline" }));
    return { abort() {} };
  } } } });
  const { result, callbacks } = capture();
  await load("api/chatStream.ts").receiveChatStream("/chat/stream", {}, params, callbacks);
  assert.equal(count, 1);
  assert.equal(result.errors.length, 1);
});
