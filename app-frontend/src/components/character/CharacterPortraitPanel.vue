<template>
  <view class="portraits-panel">
    <view class="portraits-heading">
      <text class="portraits-title">角色立绘</text>
      <button size="mini" :disabled="busy || disabled" @tap="add">添加图片</button>
    </view>
    <text class="portraits-hint">{{ sessionId ? '手动选择用于当前故事背景，随剧情节点保存。' : '添加图片后，可在聊天侧栏选择。' }} 无需配置标签。</text>
    <text v-if="sessionId" class="portraits-hint">素材由此角色的所有故事共用；当前仅手动切换，不按情绪或开场自动切换。</text>
    <text v-if="busy" class="portraits-hint">正在同步…</text>
    <view v-if="error" class="portraits-error"><text>{{ error }}</text><button size="mini" :disabled="busy" @tap="load">重试</button></view>
    <view v-if="sessionId && selection" class="portraits-reset">
      <text>{{ selection.portrait_id === null ? '当前：沿用角色头像' : '已选择故事立绘' }}</text>
      <button size="mini" :disabled="busy || disabled" @tap="choose(null)">沿用头像</button>
    </view>
    <text v-if="!busy && !error && !portraits.length" class="portraits-hint">还没有额外立绘，继续沿用角色头像。</text>
    <view class="portraits-grid">
      <view v-for="portrait in portraits" :key="portrait.id" class="portrait-item" :class="{ selected: selection?.portrait_id === portrait.id }">
        <button class="portrait-preview" :aria-label="`预览${portrait.name}`" @tap="preview(portrait)">
          <AvatarImage class="portrait-image" :src="getAvatarUrl(portrait.image_path)" mode="aspectFit" />
        </button>
        <text class="portrait-name">{{ portrait.name }}</text>
        <button v-if="sessionId" size="mini" :disabled="busy || disabled || !selection" @tap="choose(portrait.id)">{{ selection?.portrait_id === portrait.id ? '当前立绘' : '使用此图' }}</button>
        <view class="portrait-actions">
          <button size="mini" :disabled="busy || disabled" @tap="edit(portrait)">改名</button>
          <button size="mini" :disabled="busy || disabled" @tap="remove(portrait)">删除</button>
        </view>
      </view>
    </view>
    <view v-if="editingId !== null" class="portrait-editor">
      <input v-model="editingName" :maxlength="80" placeholder="立绘名称" :disabled="busy" />
      <view class="portrait-actions"><button size="mini" :disabled="busy" @tap="editingId = null">取消</button><button size="mini" :disabled="busy || disabled || !editingName.trim()" @tap="saveName">保存名称</button></view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch, onScopeDispose } from "vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import { cardImportError } from "@/utils/characterCard";
import { getBaseUrl } from "@/api/config";
import { getPortraits, uploadPortrait, renamePortrait, deletePortrait, getPortraitSelection, setPortraitSelection } from "@/api/portraits";
import type { CharacterPortrait, PortraitSelection } from "@/types/portraits";
const props = defineProps<{ characterId: number; sessionId?: number | null; disabled?: boolean; timeline?: string }>();
const emit = defineEmits<{ (e: "changed"): void }>();
const portraits = ref<CharacterPortrait[]>([]);
const selection = ref<PortraitSelection | null>(null);
const busy = ref(false), error = ref("");
const editingId = ref<number | null>(null), editingName = ref("");
let version = 0, disposed = false;
let writing = false, refreshAfterWrite = false;
let loadedServer = getBaseUrl();
function context() {
  const token = version, cid = props.characterId, sid = props.sessionId, server = getBaseUrl();
  return { cid, sid, valid: () => !disposed && token === version && cid === props.characterId && sid === props.sessionId && server === getBaseUrl() };
}
async function load() {
  version++;
  loadedServer = getBaseUrl();
  const ctx = context();
  busy.value = true; error.value = "";
  try {
    const [library, current] = await Promise.all([getPortraits(ctx.cid), ctx.sid ? getPortraitSelection(ctx.sid) : Promise.resolve(null)]);
    if (ctx.valid()) { portraits.value = library.portraits; selection.value = current; }
  } catch (cause) {
    if (ctx.valid()) { error.value = cardImportError(cause); selection.value = null; }
  } finally { if (ctx.valid()) busy.value = false; }
}
async function mutate(action: () => Promise<unknown>) {
  if (busy.value || props.disabled) return;
  if (loadedServer !== getBaseUrl()) { await load(); return; }
  const ctx = context();
  writing = true;
  busy.value = true; error.value = "";
  let failure: unknown = null;
  try {
    await action();
  } catch (cause) {
    failure = cause;
  }
  if (!ctx.valid()) return;
  writing = false;
  if (failure === null) { editingId.value = null; emit("changed"); }
  if (failure === null || refreshAfterWrite) {
    refreshAfterWrite = false;
    const pending = load();
    const reloadContext = context();
    await pending;
    if (reloadContext.valid() && failure !== null) error.value = cardImportError(failure);
  } else {
    error.value = cardImportError(failure);
    selection.value = null;
    busy.value = false;
  }
}
function add() {
  if (busy.value || props.disabled) return;
  const ctx = context();
  uni.chooseImage({ count: 1, sizeType: ["original"], success: result => {
    if (!ctx.valid() || !result.tempFilePaths[0]) return;
    void mutate(() => uploadPortrait(ctx.cid, result.tempFilePaths[0]));
  } });
}
function choose(id: number | null) {
  const sid = props.sessionId, revision = selection.value?.revision;
  if (!sid || !revision) return;
  return mutate(() => setPortraitSelection(sid, id, revision));
}
function preview(portrait: CharacterPortrait) {
  uni.previewImage({ urls: [getAvatarUrl(portrait.image_path)] });
}
function edit(portrait: CharacterPortrait) { editingId.value = portrait.id; editingName.value = portrait.name; }
function saveName() {
  const id = editingId.value, cid = props.characterId, name = editingName.value.trim();
  if (id !== null && name) void mutate(() => renamePortrait(cid, id, name));
}
function remove(portrait: CharacterPortrait) {
  const ctx = context();
  uni.showModal({ title: "删除立绘？", content: "所有故事共用此素材。删除后，使用它的故事会回退角色头像。", success: result => {
    if (result.confirm && ctx.valid()) void mutate(() => deletePortrait(ctx.cid, portrait.id));
  } });
}
watch(() => [props.characterId, props.sessionId, getBaseUrl()], () => {
  writing = false; refreshAfterWrite = false;
  portraits.value = []; selection.value = null; editingId.value = null; void load();
}, { immediate: true });
watch(() => props.timeline, () => {
  if (writing) { refreshAfterWrite = true; return; }
  // 读取可以被新剧情替代；写入期间则保留锁定，完成后统一补刷。
  selection.value = null;
  void load();
});
onScopeDispose(() => { disposed = true; version++; });
</script>

<style scoped>
.portraits-panel { display: flex; flex-direction: column; gap: 18rpx; color: var(--app-color-text-primary, #26332e); }
.portraits-heading, .portraits-reset, .portrait-actions { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.portraits-title { font-size: 28rpx; font-weight: 600; }
.portraits-hint { font-size: 22rpx; line-height: 1.7; color: var(--app-color-text-secondary, #7c8983); }
.portraits-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16rpx; }
.portrait-item { padding: 12rpx; border: 2rpx solid var(--app-color-border, #e1e8e2); border-radius: 16rpx; background: var(--app-color-surface-soft, #f3f6f3); display: flex; flex-direction: column; gap: 12rpx; min-width: 0; }
.portrait-item.selected { border-color: var(--app-color-primary, #4f8e7c); }
.portrait-preview { width: 100%; padding: 0; background: transparent; line-height: 1; }
.portrait-image { width: 100%; height: 240rpx; }
.portrait-name { font-size: 24rpx; overflow-wrap: anywhere; }
.portraits-reset, .portraits-error { font-size: 23rpx; line-height: 1.7; }
.portraits-error { color: var(--app-color-danger, #b94646); }
.portraits-panel button { margin: 0; font-size: 22rpx; }
.portrait-editor { padding: 16rpx; border: 1px solid var(--app-color-border, #e1e8e2); border-radius: 12rpx; }
.portrait-editor input { width: 100%; margin-bottom: 16rpx; font-size: 26rpx; }
</style>
