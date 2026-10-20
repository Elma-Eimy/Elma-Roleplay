const test = require("node:test");
const assert = require("node:assert/strict");
const { reactive, effectScope } = require("vue");
const { createLoader } = require("./helpers/load-ts.cjs");

class FakeXHR {
  status = 200;
  responseText = "";
  headers = {};
  aborted = false;
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(key, value) { this.headers[key] = value; }
  send(body) { this.body = body; }
  abort() { this.aborted = true; this.onabort?.(); }
  progress(text) { this.responseText += text; this.onprogress?.(); }
  end(text = "") { this.responseText += text; this.onload?.(); }
}
const request = (id = "a") => ({ requestId: id, placeholderId: `reply-${id}`,
  userMessageTempId: `user-${id}`, params: { session_id: 1, user_message: "你好" },
  baseUrl: "https://example.test/api/", apiKey: "secret", timestamp: 1 });
function setup() {
  const events = [], connections = [];
  const { createAppStreamTransport } = createLoader()("api/transports/appStream.ts");
  const transport = createAppStreamTransport(() => {
    const xhr = new FakeXHR(); connections.push(xhr); return xhr;
  }, (event) => events.push(event));
  transport.start(request());
  return { events, connections, transport, xhr: connections[0] };
}

test("App uses authenticated POST and shared SSE framing across arbitrary progress boundaries", () => {
  const wire = ': heartbeat\r\ndata:{"reasoning_chunk":"想🙂"}\r\n\r\ndata: {"chunk":"你好🙂"}\n\ndata: {"assistant_message_id":2}';
  for (let split = 0; split <= wire.length; split++) {
    const { xhr, events } = setup();
    xhr.progress(wire.slice(0, split)); xhr.end(wire.slice(split));
    assert.deepEqual(events.map(e => e.type), ["reasoning_chunk", "chunk", "done"]);
    assert.equal(events[1].chunk, "你好🙂");
    assert.equal(events[2].meta.assistant_message_id, 2);
    assert.ok(events.every(e => e.requestId === "a" && e.placeholderId === "reply-a"));
    assert.equal(xhr.method, "POST");
    assert.equal(xhr.url, "https://example.test/api/chat/stream");
    assert.equal(xhr.headers["X-API-Key"], "secret");
    assert.equal(JSON.parse(xhr.body).user_message, "你好");
  }
});

for (const [name, action] of [
  ["HTTP 401", xhr => { xhr.status = 401; xhr.progress('data:{"chunk":"bad"}\n\n'); xhr.end(); }],
  ["HTTP 500", xhr => { xhr.status = 500; xhr.end("server failed"); }],
  ["server error", xhr => xhr.end('data:{"error":"failed"}\n\n')],
  ["malformed JSON", xhr => xhr.end('data:{broken}\n\n')],
  ["truncated reply", xhr => xhr.end('data:{"chunk":"partial"}\n\n')],
  ["missing metadata", xhr => xhr.end('data:[DONE]\n\n')],
  ["network error", xhr => xhr.onerror()],
  ["timeout", xhr => xhr.ontimeout()],
  ["unexpected abort", xhr => xhr.abort()],
]) {
  test(`App reports ${name} once without false completion`, () => {
    const { xhr, events } = setup();
    action(xhr); xhr.onerror(); xhr.onload();
    assert.equal(events.filter(e => e.type === "error").length, 1);
    assert.equal(events.filter(e => e.type === "done").length, 0);
    if (name.startsWith("HTTP")) assert.equal(events.length, 1);
  });
}

test("App cancellation is silent and late callbacks cannot close the replacement request", () => {
  const { transport, xhr, events, connections } = setup();
  transport.start(request());
  assert.equal(connections.length, 1);
  transport.start(request("b"));
  const replacement = connections[1];
  assert.equal(xhr.aborted, true);
  xhr.end('data:{"assistant_message_id":99}\n\n'); xhr.onerror();
  replacement.progress('data:{"chunk":"new"}\n\n');
  assert.equal(replacement.aborted, false);
  replacement.end('data:{"assistant_message_id":2}\n\n');
  assert.deepEqual(events.map(e => e.requestId), ["b", "b"]);
  transport.start(request("c")); transport.start(null);
  connections[2].end('data:{"assistant_message_id":3}\n\n');
  assert.equal(events.length, 2);
});

test("renderjs bridge instances have separate transports and unmount cancels only its own request", () => {
  const connections = [], received = [[], []];
  class XHR extends FakeXHR { constructor() { super(); connections.push(this); } }
  const { createRenderjsStreamBridge } = createLoader({ globals: { XMLHttpRequest: XHR } })("api/transports/appStream.ts");
  const bridge = createRenderjsStreamBridge();
  const instances = [{}, {}];
  instances.forEach((instance, i) => bridge.methods.onStreamRequestChange.call(instance, request(String(i)), null, {
    callMethod(name, payload) { assert.equal(name, "onStreamEvent"); received[i].push(payload); },
  }));
  bridge.beforeUnmount.call(instances[0]);
  connections[0].end('data:{"assistant_message_id":1}\n\n');
  connections[1].end('data:{"assistant_message_id":2}\n\n');
  assert.equal(received[0].length, 0);
  assert.equal(received[1][0].type, "done");
});

test("logic bridge invalidates synchronously on session changes and accepts a terminal event only once", () => {
  const calls = [], toast = [];
  const store = reactive({ activeStreamRequest: request(),
    appendStreamChunk: (...args) => calls.push(args),
    completeStream: (...args) => calls.push(args),
    failStream: (...args) => calls.push(args) });
  const load = createLoader({ mocks: { "@/store/chatStore": { useChatStore: () => store } },
    globals: { uni: { showToast: v => toast.push(v) } } });
  const scope = effectScope();
  const bridge = scope.run(() => load("composables/useChatStreamBridge.ts").useChatStreamBridge());
  store.activeStreamRequest = request("b");
  bridge.onBridgeMessage({ detail: { type: "error", ...request(), error: "old" } });
  assert.equal(toast.length, 0);
  bridge.onBridgeMessage({ detail: { ...request("b"), type: "error", error: "new" } });
  bridge.onBridgeMessage({ detail: { ...request("b"), type: "error", error: "duplicate" } });
  assert.equal(calls.length, 1); assert.equal(toast.length, 1);
  store.activeStreamRequest = null;
  bridge.onBridgeMessage({ detail: { ...request("b"), type: "chunk", chunk: "late" } });
  assert.equal(calls.length, 1);
  scope.stop();
});
