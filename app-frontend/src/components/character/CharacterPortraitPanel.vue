<template>
  <view class="portraits-panel">
    <view class="portraits-heading">
      <view class="portraits-heading-main">
        <view class="portraits-title-row">
          <text class="portraits-title">角色立绘</text>
          <text v-if="portraits.length" class="portraits-count">{{ portraits.length }}</text>
          <text v-if="busy" class="portraits-sync-badge">同步中…</text>
        </view>
        <text class="portraits-hint">
          {{ sessionId ? '手动指定当前故事背景，随剧情节点保存（角色共用素材库）。' : '上传角色立绘素材后，可在聊天侧栏切换为故事背景。' }}
        </text>
      </view>
      <button
        class="portrait-btn portrait-btn-upload"
        :disabled="busy || disabled"
        @tap="add"
      >
        + 添加图片
      </button>
    </view>

    <view v-if="error" class="portraits-error">
      <text class="portraits-error-text">{{ error }}</text>
      <button class="portrait-btn portrait-btn-retry" :disabled="busy" @tap="load">重试</button>
    </view>

    <view v-if="sessionId && selection" class="portraits-status-bar">
      <view class="portraits-status-info">
        <view class="portraits-status-dot" :class="{ 'is-custom': selection.portrait_id !== null }"></view>
        <text class="portraits-status-text">
          {{ selection.portrait_id === null ? '当前背景：沿用角色默认头像' : '当前背景：已启用故事专属立绘' }}
        </text>
      </view>
      <button
        v-if="selection.portrait_id !== null"
        class="portrait-btn portrait-btn-reset"
        :disabled="busy || disabled"
        @tap="choose(null)"
      >
        恢复头像
      </button>
    </view>

    <view v-if="!busy && !error && !portraits.length" class="portraits-empty">
      <text class="portraits-empty-text">还没有额外立绘，当前默认沿用角色头像</text>
    </view>

    <view v-if="portraits.length" class="portraits-grid">
      <view
        v-for="portrait in portraits"
        :key="portrait.id"
        class="portrait-item"
        :class="{ selected: selection?.portrait_id === portrait.id }"
      >
        <button class="portrait-preview" :aria-label="`预览${portrait.name}`" @tap="preview(portrait)">
          <AvatarImage class="portrait-image" :src="getAvatarUrl(portrait.image_path)" mode="aspectFit" />
          <view v-if="selection?.portrait_id === portrait.id" class="portrait-active-pill">
            <text class="portrait-active-pill-text">使用中</text>
          </view>
        </button>

        <view v-if="editingId === portrait.id" class="portrait-editor-inline">
          <input
            v-model="editingName"
            class="portrait-editor-input"
            :maxlength="80"
            placeholder="输入立绘名称"
            :disabled="busy"
          />
          <view class="portrait-actions">
            <button
              class="portrait-btn portrait-btn-ghost"
              :disabled="busy"
              @tap="editingId = null"
            >
              取消
            </button>
            <button
              class="portrait-btn portrait-btn-primary"
              :disabled="busy || disabled || !editingName.trim()"
              @tap="saveName"
            >
              保存
            </button>
          </view>
        </view>

        <template v-else>
          <text class="portrait-name">{{ portrait.name }}</text>
          <button
            v-if="sessionId"
            class="portrait-btn portrait-btn-use"
            :class="{ 'is-active': selection?.portrait_id === portrait.id }"
            :disabled="busy || disabled || !selection || selection?.portrait_id === portrait.id"
            @tap="choose(portrait.id)"
          >
            {{ selection?.portrait_id === portrait.id ? '当前立绘' : '设为背景' }}
          </button>
          <view class="portrait-actions">
            <button
              class="portrait-btn portrait-btn-ghost"
              :disabled="busy || disabled"
              @tap="edit(portrait)"
            >
              改名
            </button>
            <button
              class="portrait-btn portrait-btn-danger"
              :disabled="busy || disabled"
              @tap="remove(portrait)"
            >
              删除
            </button>
          </view>
        </template>
      </view>
    </view>

    <button
      v-if="hasMore"
      class="portrait-btn portrait-btn-more"
      :disabled="busy || disabled"
      @tap="loadMore"
    >
      加载更多立绘
    </button>
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
const hasMore = ref(false);
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
    if (ctx.valid()) { portraits.value = library.portraits; hasMore.value = library.has_more ?? false; selection.value = current; }
  } catch (cause) {
    if (ctx.valid()) { error.value = cardImportError(cause); selection.value = null; }
  } finally { if (ctx.valid()) busy.value = false; }
}
async function loadMore() {
  if (busy.value || props.disabled || !hasMore.value) return;
  const ctx = context();
  busy.value = true; error.value = "";
  try {
    const result = await getPortraits(ctx.cid, portraits.value.length);
    if (ctx.valid()) { portraits.value.push(...result.portraits); hasMore.value = result.has_more; }
  } catch (cause) { if (ctx.valid()) error.value = cardImportError(cause); }
  finally { if (ctx.valid()) busy.value = false; }
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
  portraits.value = []; hasMore.value = false; selection.value = null; editingId.value = null; void load();
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
.portraits-panel {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
  color: var(--app-color-text-primary, #26332e);
}

.portraits-panel button::after {
  border: 0;
  display: none;
}

.portraits-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
}

.portraits-heading-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.portraits-title-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.portraits-title {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--app-color-text-primary, #26332e);
}

.portraits-count {
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  background: rgba(112, 174, 155, 0.14);
  color: #3f7e6d;
  font-size: 20rpx;
  font-weight: 600;
  line-height: 1.4;
}

.portraits-sync-badge {
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  background: rgba(38, 51, 46, 0.06);
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 20rpx;
  line-height: 1.4;
}

.portraits-hint {
  font-size: 22rpx;
  line-height: 1.55;
  color: var(--app-color-text-secondary, #7c8983);
}

/* 通用按钮重置与语义样式，避免 uni-app mini 按钮默认宽内边距导致窄列文字竖排换行 */
.portrait-btn {
  margin: 0;
  padding: 0 20rpx;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  font-size: 23rpx;
  font-weight: 600;
  line-height: 1;
  border-radius: 12rpx;
  border: none;
  box-sizing: border-box;
  transition: opacity 0.16s ease, background-color 0.16s ease, color 0.16s ease;
}

.portrait-btn[disabled] {
  opacity: 0.48;
}

.portrait-btn-upload {
  flex-shrink: 0;
  height: 56rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: rgba(112, 174, 155, 0.15);
  color: #3b7666;
  font-size: 23rpx;
}

.portraits-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14rpx;
  padding: 14rpx 18rpx;
  border-radius: 14rpx;
  background: rgba(217, 101, 93, 0.08);
  border: 2rpx solid rgba(217, 101, 93, 0.2);
}

.portraits-error-text {
  flex: 1;
  min-width: 0;
  font-size: 22rpx;
  line-height: 1.5;
  color: var(--app-color-danger, #c6534c);
}

.portrait-btn-retry {
  flex-shrink: 0;
  height: 48rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: rgba(217, 101, 93, 0.14);
  color: #b94646;
  font-size: 22rpx;
}

.portraits-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14rpx;
  padding: 14rpx 18rpx;
  border-radius: 16rpx;
  background: var(--app-color-surface-soft, #f3f6f4);
  border: 2rpx solid rgba(38, 51, 46, 0.06);
}

.portraits-status-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.portraits-status-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
  flex-shrink: 0;
  background: #a5b4ae;
}

.portraits-status-dot.is-custom {
  background: #4f8e7c;
  box-shadow: 0 0 0 4rpx rgba(112, 174, 155, 0.2);
}

.portraits-status-text {
  font-size: 23rpx;
  font-weight: 500;
  color: #46544e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.portrait-btn-reset {
  flex-shrink: 0;
  height: 48rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: #ffffff;
  color: #4c5d56;
  font-size: 22rpx;
  border: 2rpx solid rgba(38, 51, 46, 0.1);
}

.portraits-empty {
  padding: 28rpx 20rpx;
  border-radius: 16rpx;
  background: var(--app-color-surface-soft, #f5f7f5);
  border: 2rpx dashed rgba(38, 51, 46, 0.1);
  text-align: center;
}

.portraits-empty-text {
  font-size: 23rpx;
  color: var(--app-color-text-secondary, #7c8983);
}

.portraits-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16rpx;
}

.portrait-item {
  padding: 14rpx;
  border: 2rpx solid var(--app-color-border, #e2e9e4);
  border-radius: 20rpx;
  background: #ffffff;
  box-shadow: 0 4rpx 14rpx rgba(25, 35, 31, 0.03);
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  min-width: 0;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease;
}

.portrait-item.selected {
  border-color: var(--app-color-primary, #62a390);
  background: linear-gradient(180deg, rgba(112, 174, 155, 0.07) 0%, #ffffff 100%);
  box-shadow: 0 8rpx 20rpx rgba(79, 142, 124, 0.12);
}

.portrait-preview {
  position: relative;
  width: 100%;
  margin: 0;
  padding: 8rpx;
  border-radius: 14rpx;
  background: linear-gradient(180deg, #f3f6f4 0%, #eaf0ec 100%);
  line-height: 1;
  overflow: hidden;
  box-sizing: border-box;
}

.portrait-image {
  width: 100%;
  height: 228rpx;
  display: block;
}

.portrait-active-pill {
  position: absolute;
  top: 10rpx;
  right: 10rpx;
  padding: 4rpx 12rpx;
  border-radius: 999rpx;
  background: rgba(59, 118, 102, 0.9);
  box-shadow: 0 4rpx 10rpx rgba(22, 46, 39, 0.18);
}

.portrait-active-pill-text {
  font-size: 19rpx;
  font-weight: 600;
  color: #ffffff;
  line-height: 1.2;
}

.portrait-name {
  font-size: 24rpx;
  font-weight: 600;
  color: #2f3b36;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 2rpx;
}

.portrait-btn-use {
  width: 100%;
  height: 54rpx;
  padding: 0 12rpx;
  border-radius: 12rpx;
  background: rgba(112, 174, 155, 0.14);
  color: #3b7666;
  font-size: 23rpx;
}

.portrait-btn-use.is-active {
  background: rgba(112, 174, 155, 0.22);
  color: #2f6355;
  opacity: 1;
}

.portrait-actions {
  display: flex;
  align-items: center;
  gap: 10rpx;
  width: 100%;
}

.portrait-actions .portrait-btn {
  flex: 1;
  height: 48rpx;
  padding: 0 8rpx;
  font-size: 22rpx;
  border-radius: 10rpx;
}

.portrait-btn-ghost {
  background: #f1f5f2;
  color: #55635d;
  font-weight: 500;
}

.portrait-btn-danger {
  background: rgba(217, 101, 93, 0.1);
  color: #c6534c;
  font-weight: 500;
}

.portrait-btn-primary {
  background: #62a390;
  color: #ffffff;
}

.portrait-editor-inline {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.portrait-editor-input {
  width: 100%;
  height: 56rpx;
  padding: 0 14rpx;
  border-radius: 10rpx;
  background: #f5f8f6;
  border: 2rpx solid rgba(98, 163, 144, 0.45);
  font-size: 23rpx;
  color: #26332e;
  box-sizing: border-box;
}

.portrait-btn-more {
  width: 100%;
  height: 60rpx;
  border-radius: 14rpx;
  background: var(--app-color-surface-soft, #f3f6f4);
  color: #4c5d56;
  font-size: 23rpx;
}
</style>
