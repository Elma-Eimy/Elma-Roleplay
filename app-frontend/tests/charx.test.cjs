const test = require("node:test");
const assert = require("node:assert/strict");
const { ref, effectScope, nextTick } = require("vue");
const { createLoader, deferred } = require("./helpers/load-ts.cjs");
const flush = async () => { for (let i = 0; i < 8; i++) await nextTick(); };
const preview = token => ({ token, expires_at: 9999999999, card: { name: "包中角色", description: "设定" },
  assets: [{ index: 0, name: "main", type: "icon" }, { index: 1, name: "happy", type: "x-risu-asset" }], warnings: [], skipped_count: 0 });

for (const platform of ["H5", "MP-WEIXIN"]) {
  test(`CHARX picker rejects oversized files before upload (${platform})`, async () => {
    const method = platform === "H5" ? "chooseFile" : "chooseMessageFile";
    const load = createLoader({ platform, globals: { uni: { [method]: options => options.success({
      tempFilePaths: ["test.charx"], tempFiles: [{ name: "test.charx", path: "test.charx", size: 21 * 1024 * 1024 }],
    }) } } });
    await assert.rejects(load("utils/chooseCharx.ts").chooseCharx(), /20 MB/);
  });
  test(`CHARX picker accepts a supported ZIP and handles cancellation (${platform})`, async () => {
    const method = platform === "H5" ? "chooseFile" : "chooseMessageFile";
    let cancel = false;
    const load = createLoader({ platform, globals: { uni: { [method]: options => cancel ? options.fail({ errMsg: "cancel" }) : options.success({
      tempFilePaths: ["test.zip"], tempFiles: [{ name: "test.zip", path: "test.zip", size: 100 }],
    }) } } });
    const api = load("utils/chooseCharx.ts");
    assert.equal((await api.chooseCharx()).path, "test.zip");
    cancel = true;
    assert.equal(await api.chooseCharx(), null);
  });
}

test("App explicitly explains the unsupported archive picker", async () => {
  const api = createLoader({ platform: "APP-PLUS" })("utils/chooseCharx.ts");
  await assert.rejects(api.chooseCharx(), /H5/);
});

test("CHARX APIs use authenticated upload, shared requests and bounded preview pagination", async () => {
  const requests = [], uploads = [];
  const api = createLoader({ mocks: { "./config": {
    USE_MOCK: false, getBaseUrl: () => "https://server.test", getHeaders: () => ({ "X-API-Key": "test-key" }),
    request: async (...args) => { requests.push(args); return {}; },
  } }, globals: { uni: { uploadFile: options => { uploads.push(options); options.success({ statusCode: 200, data: JSON.stringify(preview("abc")) }); } } } })("api/charx.ts");
  await api.previewCharx("tmp.charx");
  await api.getCharxImages("abc", 12);
  await api.importCharx("abc", { character_id: 7, name: null, portrait_indices: [1], avatar_index: null });
  await api.cancelCharx("abc");
  assert.equal(uploads[0].url, "https://server.test/characters/charx/preview");
  assert.equal(uploads[0].header["X-API-Key"], "test-key");
  assert.equal(requests[0][0], "/characters/charx/previews/abc/images?offset=12");
  assert.equal(requests[1][1].method, "POST");
  assert.equal(JSON.parse(requests[1][1].body).avatar_index, null);
  assert.equal(requests[2][0], "/characters/charx/previews/abc/cancel");
  const offline = createLoader({ mocks: { "./config": { USE_MOCK: true } } })("api/charx.ts");
  await assert.rejects(offline.previewCharx("tmp.charx"), /离线模式/);
});

function fixture(api = {}, targetId = null) {
  const id = ref(targetId), releases = [], saves = [], imports = [];
  let server = "https://one.test";
  const scope = effectScope();
  const load = createLoader({ mocks: {
    "@/api/config": { getBaseUrl: () => server },
    "@/utils/chooseCharx": { chooseCharx: async () => ({ path: "test.charx", name: "test.charx", size: 100 }) },
    "@/utils/characterCard": { cardImportError: String },
    "@/api/charx": {
      previewCharx: async () => preview("preview-token"),
      getCharxImages: async () => ({ images: [{ index: 0, thumbnail: "data:image/png;base64,AAAA" }], has_more: false }),
      cancelCharx: async token => releases.push(token),
      getCharxStatus: async () => ({ status: "ready" }),
      importCharx: async (...args) => { saves.push(args); return { character_id: 7, created: id.value === null, portraits_added: 1 }; },
      ...api,
    },
  } });
  const state = scope.run(() => load("composables/useCharxImport.ts").useCharxImport(() => id.value, result => imports.push(result)));
  return { ...state, id, scope, releases, saves, imports, setServer: value => { server = value; } };
}

test("new imports suggest the main icon while existing characters preserve their avatar", async () => {
  const fresh = fixture();
  await fresh.choose();
  assert.equal(fresh.avatar.value, 0);
  assert.equal(fresh.selected.value.length, 0);
  fresh.selected.value = [1];
  await fresh.save();
  assert.deepEqual(JSON.parse(JSON.stringify(fresh.saves[0][1])), { operation: "create_character", skip_duplicates: true, character_id: null, name: "包中角色", portrait_indices: [1], avatar_index: 0 });
  assert.equal(fresh.imports[0].character_id, 7);
  fresh.scope.stop();
  const existing = fixture({}, 9);
  await existing.choose();
  assert.equal(existing.avatar.value, null);
  existing.selected.value = [1];
  await existing.save();
  assert.equal(existing.saves[0][1].character_id, 9);
  assert.equal(existing.saves[0][1].name, null);
  existing.scope.stop();
});

test("closing during upload cleans a late preview without updating UI", async () => {
  const upload = deferred();
  const state = fixture({ previewCharx: () => upload.promise });
  const pending = state.choose();
  await flush();
  state.scope.stop();
  upload.resolve(preview("late-token"));
  await pending;
  assert.equal(state.preview.value, null);
  assert.deepEqual(state.releases, ["late-token"]);
});

test("switching target discards old thumbnails and releases its preview", async () => {
  const page = deferred();
  let reads = 0;
  const state = fixture({ getCharxImages: () => ++reads === 1 ? Promise.resolve({ images: [], has_more: true }) : page.promise });
  await state.choose();
  const pending = state.loadPage(1);
  state.id.value = 2;
  await flush();
  page.resolve({ images: [{ index: 1, thumbnail: "old" }], has_more: false });
  await pending;
  assert.equal(state.preview.value, null);
  assert.equal(Object.keys(state.thumbnails.value).length, 0);
  assert.deepEqual(state.releases, ["preview-token"]);
  state.scope.stop();
});

test("late upload after server change never sends its token to the replacement server", async () => {
  const upload = deferred();
  const state = fixture({ previewCharx: () => upload.promise });
  const pending = state.choose();
  await flush();
  state.setServer("https://two.test");
  upload.resolve(preview("old-server-token"));
  await pending;
  assert.equal(state.preview.value, null);
  assert.deepEqual(state.releases, []);
  assert.equal(state.busy.value, false);
  assert.match(state.error.value, /服务器已变化/);
  state.scope.stop();
});

test("changing servers never sends an existing preview token to the new thumbnail endpoint", async () => {
  let reads = 0;
  const state = fixture({ getCharxImages: async () => { reads++; return { images: [], has_more: true }; } });
  await state.choose();
  state.setServer("https://two.test");
  await state.loadPage(1);
  assert.equal(reads, 1);
  assert.equal(state.preview.value, null);
  assert.equal(state.busy.value, false);
  assert.deepEqual(state.releases, []);
  state.scope.stop();
});

test("failed confirmation keeps the same preview for idempotent retry", async () => {
  let calls = 0;
  const tokens = [];
  const state = fixture({ importCharx: async token => {
    tokens.push(token);
    if (++calls === 1) throw new Error("network interrupted");
    return { character_id: 7, created: true, portraits_added: 0 };
  } });
  await state.choose();
  await state.save();
  assert.equal(state.preview.value.token, "preview-token");
  assert.equal(state.recoveryNeeded.value, true);
  assert.match(state.error.value, /选择已锁定/);
  await state.save();
  assert.deepEqual(tokens, ["preview-token", "preview-token"]);
  assert.equal(state.imports.length, 1);
  state.scope.stop();
});


test("lost confirmation response recovers the committed receipt without another import", async () => {
  let calls = 0;
  const state = fixture({ importCharx: async () => { calls++; throw new Error("network interrupted"); },
    getCharxStatus: async () => ({ status: "imported", result: { character_id: 42, created: true, portraits_added: 1, duplicates_skipped: 1 } }),
  });
  await state.choose();
  await state.save();
  assert.equal(calls, 1);
  assert.equal(state.imports[0].character_id, 42);
  assert.equal(state.preview.value, null);
  assert.equal(state.recoveryNeeded.value, false);
  state.scope.stop();
});

test("uncertain confirmation retries its frozen request even if reactive inputs change", async () => {
  const requests = [];
  const state = fixture({ importCharx: async (_, body) => {
    requests.push(JSON.parse(JSON.stringify(body)));
    if (requests.length === 1) throw new Error("network interrupted");
    return { character_id: 7, created: true, portraits_added: 0 };
  }, getCharxStatus: async () => { throw new Error("offline"); } });
  await state.choose();
  await state.save();
  state.selected.value = [1]; state.name.value = "changed";
  await state.save();
  assert.deepEqual(requests[1], requests[0]);
  state.scope.stop();
});

test("expired recovery releases the UI for a new upload", async () => {
  const state = fixture({ importCharx: async () => { throw new Error("offline"); }, getCharxStatus: async () => ({ status: "expired" }) });
  await state.choose(); await state.save();
  assert.equal(state.preview.value, null);
  assert.equal(state.saving.value, false);
  assert.equal(state.busy.value, false);
  assert.equal(state.recoveryNeeded.value, false);
  assert.match(state.error.value, /失效/);
  state.scope.stop();
});


test("late status recovery cannot update a replacement server or leave the UI busy", async () => {
  const reply = deferred();
  const state = fixture({ getCharxStatus: () => reply.promise });
  await state.choose();
  const pending = state.recover();
  state.setServer("https://replacement.test");
  reply.resolve({ status: "imported", result: { character_id: 77 } });
  await pending;
  assert.equal(state.imports.length, 0);
  assert.equal(state.busy.value, false);
  assert.equal(state.preview.value, null);
  assert.deepEqual(state.releases, []);
  state.scope.stop();
});

test("validation errors unlock corrections only after checking the receipt", async () => {
  const state = fixture({ importCharx: async () => { throw new Error("[API Error 409] duplicate name"); } });
  await state.choose(); await state.save();
  assert.equal(state.recoveryNeeded.value, false);
  assert.match(state.error.value, /duplicate name/);

  const offsets = [];
  const manyAssets = Array.from({ length: 14 }, (_, index) => ({
    index,
    name: index === 1 ? "角色.happy.png" : `img_${index}`,
    type: index === 0 ? "icon" : index < 12 ? "emotion" : "background",
    uri: `embeded://assets/${index}.png`,
    referenced: index === 1,
  }));
  const cachedState = fixture({
    previewCharx: async () => ({ ...preview("cache-token"), assets: manyAssets }),
    getCharxImages: async (_, offset) => {
      offsets.push(offset);
      return {
        images: manyAssets.slice(offset, offset + 12).map(a => ({ index: a.index, thumbnail: `thumb_${a.index}` })),
        has_more: offset + 12 < manyAssets.length,
      };
    },
  });
  await cachedState.choose();
  assert.deepEqual(offsets, [0]);
  await cachedState.loadPage(1);
  assert.deepEqual(offsets, [0, 12]);
  assert.equal(cachedState.thumbnails.value[0], "thumb_0");
  assert.equal(cachedState.thumbnails.value[13], "thumb_13");
  await cachedState.loadPage(0);
  assert.deepEqual(offsets, [0, 12]);

  cachedState.assetType.value = "referenced";
  await flush();
  assert.deepEqual([...cachedState.filteredAssets.value.map(a => a.index)], [1]);
  cachedState.selectFiltered();
  assert.deepEqual([...cachedState.selected.value], [1]);

  cachedState.assetType.value = "background";
  await flush();
  cachedState.selectFiltered();
  assert.deepEqual([...cachedState.selected.value], [1, 12, 13]);
  cachedState.deselectFiltered();
  assert.deepEqual([...cachedState.selected.value], [1]);
  cachedState.scope.stop();

  const existing = fixture({
    previewCharx: async () => ({
      ...preview("update-token"),
      card: { name: "包中角色", description: "新设定", extensions: { character_book: { entries: [{ content: "lore" }] } } },
    }),
  }, 9);
  await existing.choose();
  assert.equal(existing.hasEmbeddedLorebook.value, true);
  existing.cardMode.value = "fill";
  existing.syncLorebook.value = true;
  existing.greetingIndex.value = 1;
  await existing.save();
  assert.deepEqual(JSON.parse(JSON.stringify(existing.saves[0][1])), {
    operation: "update_character",
    skip_duplicates: true,
    character_id: 9,
    name: null,
    portrait_indices: [],
    avatar_index: null,
    greeting_index: 1,
    card_mode: "fill",
    sync_lorebook: true,
  });
  existing.scope.stop();
  state.scope.stop();
});


test("unchecked lorebook switch is explicit when replacing a card", async () => {
  const state = fixture({}, 9);
  await state.choose();
  state.cardMode.value = "replace";
  await state.save();
  assert.equal(state.saves[0][1].sync_lorebook, false);
  state.scope.stop();
});

test("a changed query during pagination discards the old page and loads the current filter", async () => {
  const pending = deferred();
  const assets = Array.from({length: 25}, (_, index) => ({index, name: `image${index}`, type: "icon", uri: `embeded://${index}.png`}));
  let reads = 0;
  const state = fixture({
    previewCharx: async () => ({...preview("filter-race"), assets}),
    getCharxImages: async (_, offset) => {
      reads++;
      if (reads === 2) return pending.promise;
      return {images: assets.slice(offset, offset + 12).map(a => ({index: a.index, thumbnail: `thumb${a.index}`})), has_more: true};
    },
  });
  await state.choose();
  const loading = state.loadPage(1);
  state.assetQuery.value = "image24";
  await flush();
  pending.resolve({images: [{index:12, thumbnail:"stale"}], has_more:true});
  await loading;
  await flush();
  assert.equal(state.page.value, 0);
  assert.equal(state.thumbnails.value[24], "thumb24");
  assert.equal(state.thumbnails.value[12], undefined);
  state.scope.stop();
});


test("initial upload remains busy until a changed filter finishes loading", async () => {
  const first = deferred(), latest = deferred();
  const assets = Array.from({length:25}, (_, index) => ({index,name:`image${index}`,type:"icon"}));
  let reads = 0, done = false;
  const state = fixture({
    previewCharx: async () => ({...preview("initial-filter"),assets}),
    getCharxImages: () => ++reads === 1 ? first.promise : latest.promise,
  });
  const choosing = state.choose().then(() => { done = true; });
  await flush();
  state.assetQuery.value = "image24";
  await flush();
  first.resolve({images:[{index:0,thumbnail:"old"}],has_more:true});
  await flush();
  assert.equal(reads,2);
  assert.equal(state.busy.value,true);
  assert.equal(done,false);
  await state.save();
  assert.equal(state.saves.length,0);
  latest.resolve({images:[{index:24,thumbnail:"latest"}],has_more:false});
  await choosing;
  assert.equal(state.busy.value,false);
  assert.equal(state.thumbnails.value[24],"latest");
  state.scope.stop();
});
