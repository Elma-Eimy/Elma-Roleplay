const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");

const loadUtils = createLoader({
  mocks: { "@/api/characters": { parseCharacter() {} } },
});

const {
  coerceRawLorebookEntries,
  buildCharacterLorebookEntries,
  filterLorebookEntries,
  resolveCharacterLorebookRefs,
} = loadUtils("utils/lorebookDisplay.ts");

const { getEmbeddedEntries } = loadUtils("utils/characterCard.ts");
const plain = (value) => JSON.parse(JSON.stringify(value));

test("coerces dictionary and array character_book entries in numeric key order", () => {
  const dictEntries = {
    "10": { key: "tower, bell", entry: "Old clocktower", order: 30, disable: true },
    "2": {
      key: ["harbor"],
      keysecondary: ["night"],
      value: "Fog rolls across the pier",
      constant_activation: true,
      extensions: { position: 4, depth: 2 },
      comment: "港口氛围",
    },
  };

  const coerced = coerceRawLorebookEntries(dictEntries);
  assert.equal(coerced.length, 2);
  assert.equal(coerced[0].comment, "港口氛围");
  assert.equal(coerced[1].entry, "Old clocktower");

  const card = {
    name: "Aria",
    description: "Desc",
    extensions: {
      character_book: {
        name: "汐城志",
        entries: dictEntries,
      },
    },
  };

  assert.equal(getEmbeddedEntries(card).length, 2);

  const summary = buildCharacterLorebookEntries(card, [
    {
      id: 9,
      name: "通用魔法规则",
      description: "",
      entries_count: 1,
      entries: [
        {
          keys: ["法术"],
          secondary_keys: [],
          content: "施法需要咏唱时间。",
          enabled: true,
          constant: false,
          case_sensitive: false,
          selective: false,
          position: "after_char",
          insertion_order: 200,
        },
      ],
    },
  ]);

  assert.equal(summary.embeddedName, "汐城志");
  assert.equal(summary.totalCount, 3);
  assert.equal(summary.activeCount, 2);

  const [first, second, third] = summary.entries;
  assert.equal(first.sourceName, "专属 · 汐城志");
  assert.deepEqual(plain(first.keys), ["harbor"]);
  assert.deepEqual(plain(first.secondary_keys), ["night"]);
  assert.equal(first.constant, true);
  assert.equal(first.enabled, true);
  assert.equal(first.position, "按深度插入");
  assert.equal(first.depth, 2);

  assert.deepEqual(plain(second.keys), ["tower", "bell"]);
  assert.equal(second.content, "Old clocktower");
  assert.equal(second.priority, 30);
  assert.equal(second.enabled, false);

  assert.equal(third.sourceType, "bound");
  assert.equal(third.sourceLorebookId, 9);
  assert.equal(third.position, "角色设定后");
});

test("filterLorebookEntries matches keys, secondary_keys, comments, content, and source names", () => {
  const summary = buildCharacterLorebookEntries(
    {
      extensions: {
        character_book: {
          name: "王都档案",
          entries: [
            { keys: ["骑士团"], secondary_keys: ["银徽"], content: "守卫北门", comment: "阵营条目" },
            { keys: ["酒馆"], content: "麦酒与谣言" },
          ],
        },
      },
    },
    [],
  );

  assert.equal(filterLorebookEntries(summary.entries, "").length, 2);
  assert.equal(filterLorebookEntries(summary.entries, "银徽").length, 1);
  assert.equal(filterLorebookEntries(summary.entries, "阵营").length, 1);
  assert.equal(filterLorebookEntries(summary.entries, "谣言").length, 1);
  assert.equal(filterLorebookEntries(summary.entries, "王都").length, 2);
  assert.equal(filterLorebookEntries(summary.entries, "不存在").length, 0);
});

test("resolveCharacterLorebookRefs and mock bind/unbind keep character.lorebooks synchronized", async () => {
  let db = {
    characters: [
      {
        id: 1,
        name: "Aria",
        avatar_path: "",
        description: "Desc",
        created_at: "2026-01-01T00:00:00Z",
        extensions: { lorebook_ids: [10, 999] },
      },
    ],
    sessions: [],
    messages: {},
    lorebooks: [
      {
        id: 10,
        name: "初始设定集",
        description: "",
        entries_count: 1,
        entries: [
          {
            keys: ["开篇"],
            content: "初始规则",
            enabled: true,
            constant: true,
            case_sensitive: false,
            selective: false,
            secondary_keys: [],
            position: "after_char",
            insertion_order: 100,
          },
        ],
      },
      {
        id: 20,
        name: "扩展百科",
        description: "",
        entries_count: 0,
        entries: [],
      },
    ],
  };

  const config = {
    USE_MOCK: true,
    request: async () => ({}),
    getBaseUrl: () => "http://127.0.0.1:8000",
    getHeaders: () => ({}),
    DEFAULT_HEADERS: { "Content-Type": "application/json" },
    getMockDB: () => db,
    setMockDB: (next) => {
      db = next;
    },
  };

  const loadApi = createLoader({ mocks: { "./config": config } });
  const lorebooksApi = loadApi("api/lorebooks.ts");
  const charactersApi = loadApi("api/characters.ts");

  assert.deepEqual(
    JSON.parse(JSON.stringify(resolveCharacterLorebookRefs(db.characters[0], db.lorebooks))),
    [{ id: 10, name: "初始设定集" }],
  );

  let charDetail = await charactersApi.getCharacter(1);
  assert.deepEqual(JSON.parse(JSON.stringify(charDetail.lorebooks)), [{ id: 10, name: "初始设定集" }]);

  await lorebooksApi.bindLorebook(1, 20);
  charDetail = await charactersApi.getCharacter(1);
  assert.deepEqual(JSON.parse(JSON.stringify(charDetail.lorebooks)), [
    { id: 10, name: "初始设定集" },
    { id: 20, name: "扩展百科" },
  ]);

  await lorebooksApi.updateLorebook(20, { name: "扩展百科·修订", entries: [] });
  assert.deepEqual(JSON.parse(JSON.stringify(db.characters[0].lorebooks)), [
    { id: 10, name: "初始设定集" },
    { id: 20, name: "扩展百科·修订" },
  ]);

  await lorebooksApi.unbindLorebook(1, 10);
  charDetail = await charactersApi.getCharacter(1);
  assert.deepEqual(JSON.parse(JSON.stringify(charDetail.lorebooks)), [{ id: 20, name: "扩展百科·修订" }]);

  await lorebooksApi.deleteLorebook(20);
  charDetail = await charactersApi.getCharacter(1);
  assert.deepEqual(JSON.parse(JSON.stringify(charDetail.lorebooks)), []);
});
