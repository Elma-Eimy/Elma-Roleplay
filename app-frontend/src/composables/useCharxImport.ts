import { ref, watch, onScopeDispose } from "vue";
import { getBaseUrl } from "@/api/config";
import { previewCharx, getCharxImages, cancelCharx, importCharx, getCharxStatus } from "@/api/charx";
import { chooseCharx } from "@/utils/chooseCharx";
import { cardImportError } from "@/utils/characterCard";
import type { CharxPreview, CharxImportResult, CharxImportRequest } from "@/types/charx";

export function useCharxImport(target: () => number | null, imported: (result: CharxImportResult) => void) {
  const preview = ref<CharxPreview | null>(null);
  const selected = ref<number[]>([]), avatar = ref<number | null>(null), name = ref("");
  const thumbnails = ref<Record<number, string>>({}), page = ref(0);
  const busy = ref(false), saving = ref(false), error = ref("");
  const skipDuplicates = ref(true), recoveryNeeded = ref(false);
  let pendingRequest: CharxImportRequest | null = null;
  let generation = 0, disposed = false, ownerServer = getBaseUrl();
  function release(token: string | undefined, server: string) {
    if (token && server === getBaseUrl()) void cancelCharx(token).catch(() => {});
  }
  function reset() {
    generation++;
    release(preview.value?.token, ownerServer);
    ownerServer = getBaseUrl();
    preview.value = null; selected.value = []; avatar.value = null; thumbnails.value = {}; page.value = 0;
    busy.value = false; saving.value = false; error.value = "";
    pendingRequest = null; recoveryNeeded.value = false; skipDuplicates.value = true;
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
    const ctx = context();
    busy.value = true; error.value = "";
    try {
      const result = await getCharxImages(token, value * 12);
      if (ctx.valid()) { page.value = value; thumbnails.value = Object.fromEntries(result.images.map(image => [image.index, image.thumbnail])); }
    } catch (cause) { if (ctx.valid()) { thumbnails.value = {}; error.value = cardImportError(cause); } }
    finally {
      if (ctx.valid()) busy.value = false;
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
    pendingRequest ??= { operation: target() === null ? "create_character" : "append_assets",
      skip_duplicates: skipDuplicates.value, character_id: target(), name: target() === null ? name.value.trim() : null,
      portrait_indices: [...selected.value], avatar_index: avatar.value };
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
  watch(target, reset);
  onScopeDispose(() => { reset(); disposed = true; });
  return { preview, selected, avatar, name, thumbnails, page, busy, saving, error, skipDuplicates, recoveryNeeded, choose, loadPage, save, recover };
}
