import { ref, computed, watch, onScopeDispose } from "vue";
import { getBaseUrl } from "@/api/config";
import { previewCharx, getCharxImages, cancelCharx, importCharx, getCharxStatus } from "@/api/charx";
import { chooseCharx } from "@/utils/chooseCharx";
import { cardImportError } from "@/utils/characterCard";
import type { CharxPreview, CharxImportResult, CharxImportRequest, CharxCardMode } from "@/types/charx";

export function useCharxImport(target: () => number | null, imported: (result: CharxImportResult) => void) {
  const preview = ref<CharxPreview | null>(null);
  const selected = ref<number[]>([]), avatar = ref<number | null>(null), name = ref("");
  const thumbnails = ref<Record<number, string>>({}), page = ref(0);
  const busy = ref(false), saving = ref(false), error = ref("");
  const skipDuplicates = ref(true), recoveryNeeded = ref(false);
  const greetingIndex = ref<number | null>(null);
  const cardMode = ref<CharxCardMode>("keep"), syncLorebook = ref(false);
  const assetType = ref("all"), assetQuery = ref("");
  let loadedOffsets = new Set<number>();
  let pendingRequest: CharxImportRequest | null = null;
  let generation = 0, disposed = false, ownerServer = getBaseUrl();

  const hasEmbeddedLorebook = computed(() => {
    const book = preview.value?.card.extensions?.character_book as { entries?: unknown[] } | undefined;
    return Array.isArray(book?.entries) && (book?.entries.length ?? 0) > 0;
  });

  const assetTypes = computed(() => {
    const assets = preview.value?.assets || [];
    const tabs: { key: string; label: string; count: number }[] = [{ key: "all", label: "全部", count: assets.length }];
    const refCount = assets.filter(asset => asset.referenced).length;
    if (refCount > 0) tabs.push({ key: "referenced", label: "正文引用", count: refCount });
    const counts = new Map<string, number>();
    for (const asset of assets) counts.set(asset.type, (counts.get(asset.type) || 0) + 1);
    for (const [type, count] of counts.entries()) tabs.push({ key: type, label: type, count });
    return tabs;
  });

  const filteredAssets = computed(() => {
    const assets = preview.value?.assets || [];
    const query = assetQuery.value.trim().toLowerCase();
    return assets.filter(asset => {
      if (assetType.value === "referenced" && !asset.referenced) return false;
      if (assetType.value !== "all" && assetType.value !== "referenced" && asset.type !== assetType.value) return false;
      if (!query) return true;
      return asset.name.toLowerCase().includes(query) || (asset.uri || "").toLowerCase().includes(query) || asset.type.toLowerCase().includes(query);
    });
  });

  function selectFiltered() {
    const existing = new Set(selected.value);
    const additions = filteredAssets.value.map(asset => asset.index).filter(index => !existing.has(index));
    if (additions.length) selected.value = [...selected.value, ...additions];
  }

  function deselectFiltered() {
    const removal = new Set(filteredAssets.value.map(asset => asset.index));
    if (removal.size) selected.value = selected.value.filter(index => !removal.has(index));
  }

  function release(token: string | undefined, server: string) {
    if (token && server === getBaseUrl()) void cancelCharx(token).catch(() => {});
  }
  function reset() {
    generation++;
    release(preview.value?.token, ownerServer);
    ownerServer = getBaseUrl();
    loadedOffsets = new Set<number>();
    preview.value = null; selected.value = []; avatar.value = null; thumbnails.value = {}; page.value = 0;
    busy.value = false; saving.value = false; error.value = "";
    pendingRequest = null; recoveryNeeded.value = false; skipDuplicates.value = true;
    greetingIndex.value = null; cardMode.value = "keep"; syncLorebook.value = false;
    assetType.value = "all"; assetQuery.value = "";
  }
  function context() {
    const version = generation, id = target(), server = getBaseUrl();
    const current = () => !disposed && version === generation && id === target();
    return { server, current, valid: () => current() && server === getBaseUrl() };
  }
  async function loadPage(value: number) {
    if (ownerServer !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; return; }
    const token = preview.value?.token;
    if (!token || saving.value || disposed) return;
    const allAssets = preview.value?.assets || [];
    const posMap = new Map(allAssets.map((asset, idx) => [asset.index, idx]));
    const slice = filteredAssets.value.slice(value * 12, (value + 1) * 12);
    const offsets: number[] = [];
    if (slice.length > 0) {
      for (const item of slice) {
        if (!(item.index in thumbnails.value)) {
          const pos = posMap.get(item.index) ?? 0;
          const off = Math.floor(pos / 12) * 12;
          if (!offsets.includes(off)) offsets.push(off);
        }
      }
    } else if (!loadedOffsets.has(value * 12)) {
      offsets.push(value * 12);
    }
    if (offsets.length === 0 && !error.value) {
      page.value = value;
      return;
    }
    const toFetch = offsets.length ? offsets : [value * 12];
    const ctx = context();
    const filterType = assetType.value, filterQuery = assetQuery.value;
    const sameFilter = () => filterType === assetType.value && filterQuery === assetQuery.value;
    busy.value = true; error.value = "";
    try {
      const nextThumbnails = { ...thumbnails.value };
      for (const off of toFetch) {
        const result = await getCharxImages(token, off);
        if (!ctx.valid() || !sameFilter()) return;
        for (const image of result.images) nextThumbnails[image.index] = image.thumbnail;
        loadedOffsets.add(off);
      }
      if (ctx.valid()) { page.value = value; thumbnails.value = nextThumbnails; }
    } catch (cause) { if (ctx.valid() && sameFilter()) { error.value = cardImportError(cause); } }
    finally {
      if (ctx.valid()) {
        busy.value = false;
        if (!sameFilter()) await loadPage(0);
      }
      else if (ctx.current() && ctx.server !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; }
    }
  }
  async function choose() {
    if (ownerServer !== getBaseUrl()) reset();
    if (busy.value || saving.value || recoveryNeeded.value || disposed) return;
    const ctx = context();
    busy.value = true; error.value = "";
    let uploaded: CharxPreview | null = null;
    try {
      const file = await chooseCharx();
      if (!file || !ctx.valid()) return;
      uploaded = await previewCharx(file.path);
      if (!ctx.valid()) { release(uploaded.token, ctx.server); return; }
      release(preview.value?.token, ownerServer);
      ownerServer = ctx.server;
      loadedOffsets = new Set<number>();
      thumbnails.value = {};
      greetingIndex.value = null; cardMode.value = "keep"; syncLorebook.value = false;
      assetType.value = "all"; assetQuery.value = "";
      preview.value = uploaded;
      selected.value = []; name.value = uploaded.card.name; page.value = 0;
      const icons = uploaded.assets.filter(asset => asset.type === "icon");
      avatar.value = target() === null ? (icons.find(asset => asset.name === "main") || icons[0])?.index ?? null : null;
      await loadPage(0);
    } catch (cause) { if (ctx.valid()) error.value = cardImportError(cause); }
    finally {
      if (ctx.valid()) busy.value = false;
      else if (ctx.current() && ctx.server !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; }
    }
  }
  async function save() {
    if (ownerServer !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; return; }
    if (!preview.value || busy.value || saving.value || disposed) return;
    const ctx = context(), token = preview.value.token;
    saving.value = true; error.value = "";
    if (!pendingRequest) {
      const id = target();
      const updatingCard = id !== null && (cardMode.value !== "keep" || syncLorebook.value || greetingIndex.value !== null);
      const req: CharxImportRequest = {
        operation: id === null ? "create_character" : updatingCard ? "update_character" : "append_assets",
        skip_duplicates: skipDuplicates.value,
        character_id: id,
        name: id === null ? name.value.trim() : null,
        portrait_indices: [...selected.value],
        avatar_index: avatar.value,
      };
      if (greetingIndex.value !== null) req.greeting_index = greetingIndex.value;
      if (id !== null && cardMode.value !== "keep") req.card_mode = cardMode.value;
      if (id !== null) req.sync_lorebook = syncLorebook.value;
      pendingRequest = req;
    }
    try {
      const result = await importCharx(token, pendingRequest);
      if (ctx.valid()) { preview.value = null; pendingRequest = null; recoveryNeeded.value = false; imported(result); }
    } catch (cause) {
      if (ctx.valid()) {
        error.value = cardImportError(cause);
        recoveryNeeded.value = true;
        await recover(/API Error (400|404|409|422)/.test(String(cause)));
      }
    }
    finally {
      if (ctx.valid()) saving.value = false;
      else if (ctx.current() && ctx.server !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; }
    }
  }
  async function recover(validationFailure = false) {
    if (!preview.value || disposed) return;
    if (ownerServer !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; return; }
    const ctx = context();
    busy.value = true;
    try {
      const status = await getCharxStatus(preview.value.token);
      if (!ctx.valid()) return;
      if (status.status === "imported" && status.result) {
        preview.value = null; pendingRequest = null; recoveryNeeded.value = false;
        imported(status.result);
      } else if (["expired", "cancelled", "not_found", "target_deleted"].includes(status.status)) {
        reset(); error.value = status.status === "target_deleted" ? "导入已完成，但目标角色已删除" : "预览已失效，请重新选择角色包";
      } else if (status.status === "ready" && validationFailure) {
        pendingRequest = null; recoveryNeeded.value = false;
      } else {
        error.value = "尚未确认保存结果。选择已锁定，可查询结果或重试同一次确认。";
      }
    } catch {
      if (ctx.valid()) error.value = "暂时无法查询保存结果。选择已锁定，请恢复连接后查询或重试原确认。";
    } finally {
      if (ctx.valid()) busy.value = false;
      else if (ctx.current() && ctx.server !== getBaseUrl()) { reset(); error.value = "服务器已变化，请重新选择角色包"; }
    }
  }
  watch([assetType, assetQuery], () => {
    if (!preview.value || saving.value || disposed) return;
    page.value = 0;
    if (!busy.value) void loadPage(0);
  });
  watch(target, reset);
  onScopeDispose(() => { reset(); disposed = true; });
  return {
    preview, selected, avatar, name, thumbnails, page, busy, saving, error,
    skipDuplicates, recoveryNeeded, greetingIndex, cardMode, syncLorebook,
    hasEmbeddedLorebook, assetType, assetQuery, assetTypes, filteredAssets,
    selectFiltered, deselectFiltered, choose, loadPage, save, recover,
  };
}
