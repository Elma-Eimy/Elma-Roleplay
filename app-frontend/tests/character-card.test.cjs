const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");
const load = createLoader({
  mocks: { "@/api/characters": { parseCharacter() {} } },
});
const {
  greetingOptions,
  getCardGreetings,
  mergeCharacterCard,
  getCardMetadata,
  cardImportError,
} = load("utils/characterCard.ts");
const { useCharacterCardImport } = load(
  "composables/useCharacterCardImport.ts",
);
const plain = (value) => JSON.parse(JSON.stringify(value));

test("searchable greetings retain backend indexes including blank or malformed entries", () => {
  const greetings = getCardGreetings({
    extensions: {
      alternate_greetings: [
        "✦ Night ✦\nFirst",
        "",
        null,
        "# Last\nFinal scene",
      ],
    },
  });
  const options = greetingOptions("Default story", greetings);
  assert.equal(options.length, 5);
  assert.equal(options[0].index, null);
  assert.equal(options.find((item) => item.title === "Last").index, 3);
  assert.equal(options[1].content, "✦ Night ✦\nFirst");
});

test("replacement removes old card settings while JSON retains the current portrait", () => {
  const current = {
    id: 7,
    name: "Old",
    description: "old",
    avatar_path: "old.png",
    extensions: { character_book: { entries: [1] }, vendor: 1 },
  };
  const incoming = {
    name: "New",
    description: "new",
    extensions: { alternate_greetings: ["new start"] },
  };
  const result = mergeCharacterCard(current, incoming, "replace");
  assert.equal(result.name, "New");
  assert.equal(result.avatar_path, "old.png");
  assert.equal(result.extensions.character_book, undefined);
  assert.equal(result.id, undefined);
  result.extensions.alternate_greetings.push("edit");
  assert.equal(incoming.extensions.alternate_greetings.length, 1);
  assert.equal(current.extensions.vendor, 1);
});

test("fill mode preserves existing fields and fills empty greetings and metadata without losing vendor data", () => {
  const current = {
    name: "My version",
    description: "",
    first_mes: "My start",
    tags: ["mine"],
    extensions: {
      alternate_greetings: [],
      vendor: { enabled: false, count: 0 },
      ai_roleplay_card: { creator: "" },
    },
  };
  const incoming = {
    name: "Other",
    description: "Background",
    first_mes: "Other start",
    tags: ["other"],
    extensions: {
      alternate_greetings: ["A"],
      vendor: { enabled: true, count: 2, newField: "new" },
      ai_roleplay_card: { creator: "Author", character_version: "1" },
    },
  };
  const before = JSON.stringify(current);
  const result = mergeCharacterCard(current, incoming, "fill");
  assert.equal(result.name, "My version");
  assert.equal(result.description, "Background");
  assert.equal(result.first_mes, "My start");
  assert.deepEqual(plain(result.tags), ["mine"]);
  assert.deepEqual(plain(result.extensions.alternate_greetings), ["A"]);
  assert.deepEqual(plain(result.extensions.vendor), {
    enabled: false,
    count: 0,
    newField: "new",
  });
  assert.equal(getCardMetadata(result).creator, "Author");
  assert.equal(JSON.stringify(current), before);
});

test("closing import invalidates late success and failure without changing the draft", async () => {
  for (const reject of [false, true]) {
    const pending = deferred();
    const state = useCharacterCardImport(() => pending.promise);
    const request = state.load("first.png");
    state.reset();
    reject
      ? pending.reject(new Error("network"))
      : pending.resolve({ data: { name: "Late", description: "" } });
    await request;
    assert.equal(state.card.value, null);
    assert.equal(state.error.value, "");
    assert.equal(state.loading.value, false);
  }
});

test("an older parse cannot replace the newly selected card or clear its loading state", async () => {
  const first = deferred(),
    second = deferred();
  const state = useCharacterCardImport((file) =>
    file === "a" ? first.promise : second.promise,
  );
  const a = state.load("a"),
    b = state.load("b");
  first.resolve({ data: { name: "Old", description: "" } });
  await a;
  assert.equal(state.loading.value, true);
  assert.equal(state.card.value, null);
  second.resolve({ data: { name: "New", description: "" } });
  await b;
  assert.equal(state.card.value.name, "New");
  assert.equal(state.loading.value, false);
});

test("parse errors show server guidance and cannot be applied as a card", async () => {
  const state = useCharacterCardImport(async () => {
    throw new Error(
      '[parseCharacter 错误 400]: {"detail":"PNG 中未找到角色数据"}',
    );
  });
  await state.load("photo.png");
  assert.equal(state.error.value, "PNG 中未找到角色数据");
  assert.equal(state.card.value, null);
  assert.match(cardImportError(new Error("request:fail timeout")), /连接/);
});

for (const platform of ["H5", "APP-PLUS", "MP-WEIXIN"]) {
  test(`file selection uses the platform picker and cancellation is silent (${platform})`, async () => {
    let calls = 0;
    const method =
      platform === "APP-PLUS"
        ? "chooseImage"
        : platform === "MP-WEIXIN"
          ? "chooseMessageFile"
          : "chooseFile";
    const selector = createLoader({
      platform,
      globals: {
        uni: {
          [method](options) {
            calls++;
            options.fail({ errMsg: "choose:fail cancel" });
          },
        },
      },
    })("utils/chooseCharacterCard.ts");
    assert.equal(await selector.chooseCharacterCard(), null);
    assert.equal(calls, 1);
  });
}
