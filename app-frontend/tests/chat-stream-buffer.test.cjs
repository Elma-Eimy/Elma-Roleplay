const test = require("node:test");
const assert = require("node:assert/strict");
const { createPinia, setActivePinia } = require("pinia");
const { createLoader } = require("./helpers/load-ts.cjs");

function clockFixture() {
  let nextId = 0;
  const pending = new Map();
  return {
    pending,
    globals: {
      setTimeout(callback, delay) {
        const id = ++nextId;
        pending.set(id, { callback, delay });
        return id;
      },
      clearTimeout(id) { pending.delete(id); },
    },
    tick() {
      const entry = pending.entries().next().value;
      assert.ok(entry, "expected a pending flush");
      pending.delete(entry[0]);
      entry[1].callback();
    },
  };
}

function bufferFixture() {
  const clock = clockFixture();
  const text = [], reasoning = [];
  const { createChatStreamBuffer } = createLoader({ globals: clock.globals })("utils/chatStreamBuffer.ts");
  const create = () => createChatStreamBuffer(
    (id, value) => text.push([id, value]),
    (id, value) => reasoning.push([id, value]),
  );
  return { clock, text, reasoning, create, buffer: create() };
}

test("bursts preserve text and reasoning order with a single 48ms flush", () => {
  const { buffer, clock, text, reasoning } = bufferFixture();
  buffer.appendText("one", "你");
  buffer.appendReasoning("one", "先想");
  buffer.appendText("one", "好🙂");
  buffer.appendReasoning("one", "一下");
  buffer.appendText("two", "另一条");
  assert.equal(clock.pending.size, 1);
  assert.equal([...clock.pending.values()][0].delay, 48);
  assert.deepEqual(text, []);
  clock.tick();
  assert.deepEqual(text, [["one", "你好🙂"], ["two", "另一条"]]);
  assert.deepEqual(reasoning, [["one", "先想一下"]]);
  assert.equal(clock.pending.size, 0);
});

test("explicit flush delivers the tail once and the next burst gets its own timer", () => {
  const { buffer, clock, text } = bufferFixture();
  buffer.appendText("one", "尾字");
  buffer.flush();
  buffer.flush();
  assert.deepEqual(text, [["one", "尾字"]]);
  assert.equal(clock.pending.size, 0);
  buffer.appendText("one", "下一段");
  clock.tick();
  assert.deepEqual(text, [["one", "尾字"], ["one", "下一段"]]);
});

test("clear discards both kinds of text and empty chunks do not schedule work", () => {
  const { buffer, clock, text, reasoning } = bufferFixture();
  buffer.appendText("one", "旧正文");
  buffer.appendReasoning("one", "旧思考");
  buffer.clear();
  buffer.clear();
  buffer.appendText("one", "");
  buffer.appendReasoning("one", "");
  assert.equal(clock.pending.size, 0);
  buffer.flush();
  assert.deepEqual(text, []);
  assert.deepEqual(reasoning, []);
  buffer.appendReasoning("two", "新思考");
  clock.tick();
  assert.deepEqual(reasoning, [["two", "新思考"]]);
});

test("clearing one buffer cannot discard another buffer with the same message id", () => {
  const { buffer, create, clock, text } = bufferFixture();
  const second = create();
  buffer.appendText("same", "discard");
  second.appendText("same", "keep");
  buffer.clear();
  assert.equal(clock.pending.size, 1);
  clock.tick();
  assert.deepEqual(text, [["same", "keep"]]);
});

function storeFixture(platform) {
  setActivePinia(createPinia());
  const clock = clockFixture();
  let now = 1000;
  class FixtureDate extends Date { static now() { return ++now; } }
  const load = createLoader({
    platform,
    globals: { ...clock.globals, Date: FixtureDate },
    mocks: {
      "@/api/sessions": {},
      "@/api/chat": { sendMessageStream: async () => {} },
      "@/api/config": { getBaseUrl: () => "https://example.invalid", getSavedApiKey: () => "" },
      "./personaStore": { usePersonaStore: () => ({ userNickname: "用户", applyAffectionChange() {} }) },
      "./chatSettingsStore": { useChatSettingsStore: () => ({ clearParameters() {}, activateSession() {}, $reset() {} }) },
      "@/composables/useAudioPlayer": { useAudioPlayer: () => ({ stopMessageTTS() {} }) },
    },
  });
  const store = load("store/chatStore.ts").useChatStore();
  store.setActiveSession(1);
  return { store, clock };
}

for (const platform of ["H5", "MP-WEIXIN", "APP-PLUS"]) {
  test(`${platform} completion flushes the tail and keeps server candidates authoritative`, () => {
    const { store, clock } = storeFixture(platform);
    const id = store.addStreamingPlaceholder();
    store.appendStreamChunk(id, "第一段");
    store.appendStreamReasoningChunk(id, "思考");
    assert.equal(store.messages[0].content, "");
    clock.tick();
    assert.equal(store.messages[0].content, "第一段");
    assert.equal(store.streamingText, "第一段");
    assert.equal(store.messages[0].reasoning_content, "思考");

    store.appendStreamChunk(id, "尾字");
    store.appendStreamReasoningChunk(id, "尾部思考");
    store.finalizeStream(id, { id: 8 });
    assert.equal(store.messages[0].content, "第一段尾字");
    assert.equal(store.messages[0].reasoning_content, "思考尾部思考");
    assert.equal(store.messages[0].status, "done");
    assert.equal(store.streamingText, "");
    assert.equal(clock.pending.size, 0);
    store.appendStreamChunk(id, "迟到正文");
    store.appendStreamReasoningChunk(id, "迟到思考");
    assert.equal(clock.pending.size, 0);

    const next = store.addStreamingPlaceholder();
    store.appendStreamChunk(next, "未规范化正文");
    store.appendStreamReasoningChunk(next, "流中思考");
    store.completeStream(next, {
      assistant_message_id: 9, active_index: 0,
      candidates: [{ id: 9, content: "服务器正文", reasoning_content: "服务器思考" }],
    });
    assert.equal(store.messages[1].content, "服务器正文");
    assert.equal(store.messages[1].reasoning_content, "服务器思考");
    assert.equal(clock.pending.size, 0);
    store.$reset();
    store.$dispose();
  });

  test(`${platform} session changes, reset, failure and replacement discard queued chunks`, () => {
    for (const action of ["switch", "reset", "failure", "replacement"]) {
      const { store, clock } = storeFixture(platform);
      const oldId = store.addStreamingPlaceholder();
      store.appendStreamChunk(oldId, "旧正文");
      store.appendStreamReasoningChunk(oldId, "旧思考");
      assert.equal(clock.pending.size, 1);
      if (action === "switch") store.setActiveSession(2);
      if (action === "reset") store.$reset();
      if (action === "failure") store.failStream(oldId, "failed");
      if (action === "replacement") store.addStreamingPlaceholder();
      assert.equal(clock.pending.size, 0, action);

      const next = store.addStreamingPlaceholder();
      store.appendStreamChunk(next, "新正文");
      store.appendStreamReasoningChunk(next, "新思考");
      clock.tick();
      const message = store.messages.find(message => message.tempId === next);
      assert.equal(message.content, "新正文", action);
      assert.equal(message.reasoning_content, "新思考", action);
      assert.equal(store.streamingText, "新正文", action);
      store.$reset();
      store.$dispose();
    }
  });
}
