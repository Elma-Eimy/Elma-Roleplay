const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, effectScope } = require("vue");
const { createLoader } = require("./helpers/load-ts.cjs");

function fixture(t) {
  const storage = new Map();
  let endpoint = "https://one.test";
  let listener;
  let failWrites = false;
  const notices = [];
  const session = ref(1), character = ref(4);
  const load = createLoader({
    mocks: {
      "@/api/config": { getBaseUrl: () => endpoint },
      "@/utils/connectionEvents": { onServerChange: callback => { listener = callback; return () => { listener = null; }; } },
    },
    globals: { uni: {
      getStorageSync: key => storage.get(key),
      setStorageSync: (key, value) => { if (failWrites) throw new Error("full"); storage.set(key, value); },
      showToast: notice => notices.push(notice),
    } },
  });
  const scope = effectScope();
  const book = scope.run(() => load("composables/useStoryKeepsakes.ts").useStoryKeepsakes(session, () => character.value));
  t.after(() => scope.stop());
  return { book, session, character, notices, storage, scope,
    switchServer(value) { endpoint = value; listener(); },
    failStorage() { failWrites = true; },
  };
}
const message = (content = "那就约好，下次一起看海。") => ({ id: 12, role: "assistant", content, status: "done" });

test("keepsakes snapshot completed messages, deduplicate exact candidates and survive edits", t => {
  const { book, session } = fixture(t);
  book.save({ ...message(), id: -1 }, "林间");
  book.save({ ...message(), status: "streaming" }, "林间");
  assert.equal(book.cards.value.length, 0);
  const original = message();
  book.save(original, "林间");
  book.save(original, "林间");
  assert.equal(book.cards.value.length, 1);
  assert.equal(book.isOpen.value, true);
  original.content = "已经改过的回复";
  assert.equal(book.cards.value[0].content, message().content);
  book.save(original, "林间");
  assert.equal(book.cards.value.length, 2);
  assert.notEqual(book.cards.value[0].id, book.cards.value[1].id);
  book.rename(book.cards.value[0].id, " 海边的约定 ");
  session.value = 2;
  assert.equal(book.cards.value.length, 0, "parallel stories never inherit snapshots");
  session.value = 1;
  assert.equal(book.cards.value[0].title, "海边的约定");
  book.remove(book.cards.value[0].id);
  assert.equal(book.cards.value.length, 1);
});

test("palettes follow character identity while collections follow server and story", t => {
  const { book, session, character, switchServer, scope } = fixture(t);
  book.selectPalette("rose");
  book.save(message(), "林间");
  session.value = 2;
  assert.equal(book.paletteId.value, "rose");
  character.value = 5;
  assert.equal(book.paletteId.value, "sage");
  character.value = 4;
  assert.equal(book.paletteId.value, "rose");
  book.isOpen.value = true;
  switchServer("https://two.test");
  assert.equal(book.isOpen.value, false);
  assert.equal(book.cards.value.length, 0);
  assert.equal(book.paletteId.value, "sage");
  session.value = null;
  session.value = 1;
  book.save(message("另一台服务器的片段"), "林间");
  switchServer("https://one.test");
  session.value = null;
  session.value = 1;
  assert.equal(book.cards.value[0].content, message().content);
  assert.equal(book.paletteId.value, "rose");
  scope.stop();
});

test("failed storage writes preserve the previous collection and report failure", t => {
  const { book, failStorage, notices, session, storage } = fixture(t);
  book.save(message(), "林间");
  failStorage();
  book.remove(book.cards.value[0].id);
  book.selectPalette("blue");
  assert.equal(book.cards.value.length, 1);
  assert.equal(book.paletteId.value, "sage");
  assert.equal(notices.at(-1).icon, "none");
  storage.set("story_keepsakes_v1:https://one.test:3", '{broken');
  session.value = 3;
  assert.equal(book.cards.value.length, 0);
  session.value = 1;
  assert.equal(book.cards.value.length, 1);
});
