<template>
  <view class="portraits-panel">
    <view class="portraits-heading">
      <view
        class="portraits-heading-main"
        role="button"
        :aria-expanded="!collapsed"
        @tap="collapsed = !collapsed"
      >
        <view class="portraits-title-row">
          <text class="portraits-title">成员立绘</text>
          <text v-if="options?.rows.length" class="portraits-count">{{ options.rows.length }}</text>
          <text v-if="busy" class="portraits-sync-badge">同步中…</text>
          <image
            class="portraits-chevron"
            :class="{ 'is-active': !collapsed }"
            src="/static/icons/settings_chevron.svg"
            mode="aspectFit"
          />
        </view>
        <text class="portraits-hint">
          <template v-if="collapsed">
            {{ selectedPortraitId !== null ? `${member.character.name}：已启用立绘` : `${member.character.name}：沿用角色头像` }} · 点击展开
          </template>
          <template v-else>
            {{ member.character.name }}（成员 {{ member.slot }}）独立选择，随采用候选保存。
          </template>
        </text>
      </view>
      <button
        class="portrait-btn portrait-btn-refresh"
        :disabled="busy || disabled"
        @tap.stop="refreshCurrent"
      >
        刷新
      </button>
    </view>

    <view v-if="portraitError" class="portraits-error">
      <text class="portraits-error-text">{{ portraitError }}</text>
      <button class="portrait-btn portrait-btn-retry" :disabled="busy" @tap="emit('refresh')">重试</button>
    </view>

    <template v-if="!collapsed">
      <view v-if="portraitData && !portraitData.can_update" class="portraits-lock-hint">
        <text class="portraits-lock-text">当前只可查看；请求处理完成并刷新后，才能修改最新未确认候选的选择。</text>
      </view>

      <view v-if="portraitData" class="portraits-status-bar">
        <view class="portraits-status-info">
          <view class="portraits-status-dot" :class="{ 'is-custom': selectedPortraitId !== null }"></view>
          <text class="portraits-status-text">
            {{ selectedPortraitId !== null ? '当前背景：已启用专属立绘' : '当前背景：沿用角色默认头像' }}
          </text>
        </view>
        <button
          v-if="selectedPortraitId !== null"
          class="portrait-btn portrait-btn-reset"
          :disabled="!canChoosePortrait"
          @tap="emit('choose', member.persona_id, null)"
        >
          恢复头像
        </button>
      </view>

      <view v-if="options?.error" class="portraits-error">
        <text class="portraits-error-text">{{ options.error }}</text>
        <button class="portrait-btn portrait-btn-retry" :disabled="options.loading" @tap="emit('load-options', member.persona_id, false)">重试</button>
      </view>

      <view v-else-if="options?.loading && !options.rows.length" class="portraits-empty">
        <text class="portraits-empty-text">正在读取立绘素材…</text>
      </view>

      <view v-else-if="options && !options.rows.length" class="portraits-empty">
        <text class="portraits-empty-text">还没有额外立绘，可到角色档案添加</text>
      </view>

      <view v-if="options?.rows.length" class="portraits-grid">
        <view
          v-for="portrait in options.rows"
          :key="portrait.id"
          class="portrait-item"
          :class="{ selected: selectedPortraitId === portrait.id }"
        >
          <view class="portrait-preview">
            <AvatarImage class="portrait-image" :src="getAvatarUrl(portrait.image_path)" mode="aspectFit" />
            <view v-if="selectedPortraitId === portrait.id" class="portrait-active-pill">
              <text class="portrait-active-pill-text">使用中</text>
            </view>
          </view>
          <text class="portrait-name">{{ portrait.name }}</text>
          <button
            class="portrait-btn portrait-btn-use"
            :class="{ 'is-active': selectedPortraitId === portrait.id }"
            :disabled="!canChoosePortrait || selectedPortraitId === portrait.id"
            @tap="emit('choose', member.persona_id, portrait.id)"
          >
            {{ selectedPortraitId === portrait.id ? '当前立绘' : '设为背景' }}
          </button>
        </view>
      </view>

      <button
        v-if="options?.hasMore"
        class="portrait-btn portrait-btn-more"
        :disabled="!canChoosePortrait || options.loading"
        @tap="emit('load-options', member.persona_id, true)"
      >
        {{ options.loading ? '正在加载…' : '加载更多立绘' }}
      </button>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import { getAvatarUrl } from "@/api/characters";
import type { CharacterPortrait } from "@/types/portraits";
import type { GroupPortraitsResponse, GroupSessionMember } from "@/types/groupSessions";

export interface GroupPortraitOptionBucket {
  loading: boolean;
  error: string;
  rows: CharacterPortrait[];
  hasMore: boolean;
}

const props = defineProps<{
  member: GroupSessionMember;
  portraitData: GroupPortraitsResponse | null;
  portraitOptions: Record<number, GroupPortraitOptionBucket>;
  loadingPortraits: boolean;
  portraitWriting: boolean;
  portraitError: string;
  canChoosePortrait: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "choose", personaId: number, portraitId: number | null): void;
  (e: "load-options", personaId: number, append: boolean): void;
  (e: "refresh"): void;
}>();

const collapsed = ref(true);
const busy = computed(() => props.loadingPortraits || props.portraitWriting || !!options.value?.loading);
const options = computed(() => props.portraitOptions[props.member.persona_id]);
const selectedPortraitId = computed(
  () => props.portraitData?.members.find((row) => row.persona_id === props.member.persona_id)?.portrait_id ?? null
);

watch(
  [collapsed, () => props.member.persona_id],
  ([isCollapsed, personaId]) => {
    if (!isCollapsed && !props.portraitOptions[personaId]?.rows.length && !props.portraitOptions[personaId]?.loading) {
      emit("load-options", personaId, false);
    }
  }
);

const refreshCurrent = () => {
  emit("refresh");
  if (!collapsed.value) {
    emit("load-options", props.member.persona_id, false);
  }
};
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
  cursor: pointer;
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
}

.portraits-sync-badge {
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  background: rgba(38, 51, 46, 0.06);
  color: var(--app-color-text-secondary, #64716b);
  font-size: 20rpx;
}

.portraits-chevron {
  width: 26rpx;
  height: 26rpx;
  opacity: 0.55;
  transition: transform 0.22s ease;
}

.portraits-chevron.is-active {
  transform: rotate(180deg);
}

.portraits-hint {
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 22rpx;
  line-height: 1.5;
}

.portrait-btn {
  margin: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  font-weight: 600;
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.portrait-btn:active {
  transform: scale(0.97);
}

.portrait-btn[disabled] {
  opacity: 0.45;
}

.portrait-btn-refresh {
  flex-shrink: 0;
  height: 54rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: rgba(112, 174, 155, 0.14);
  color: #3b7666;
  font-size: 23rpx;
}

.portraits-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14rpx;
  padding: 16rpx 18rpx;
  border-radius: 16rpx;
  background: rgba(217, 101, 93, 0.08);
  border: 1px solid rgba(217, 101, 93, 0.2);
}

.portraits-error-text {
  flex: 1;
  min-width: 0;
  font-size: 23rpx;
  color: #c6534c;
  line-height: 1.5;
}

.portrait-btn-retry {
  height: 48rpx;
  padding: 0 18rpx;
  border-radius: 999rpx;
  background: #ffffff;
  color: #c6534c;
  font-size: 22rpx;
  border: 1px solid rgba(217, 101, 93, 0.25);
}

.portraits-lock-hint {
  padding: 12rpx 16rpx;
  border-radius: 14rpx;
  background: rgba(214, 156, 74, 0.1);
  border: 1px solid rgba(214, 156, 74, 0.22);
}

.portraits-lock-text {
  font-size: 22rpx;
  line-height: 1.5;
  color: #8c6223;
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
}

.portrait-item.selected {
  border-color: var(--app-color-primary, #62a390);
  background: linear-gradient(180deg, rgba(112, 174, 155, 0.07) 0%, #ffffff 100%);
  box-shadow: 0 8rpx 20rpx rgba(79, 142, 124, 0.12);
}

.portrait-preview {
  position: relative;
  width: 100%;
  padding: 8rpx;
  border-radius: 14rpx;
  background: linear-gradient(180deg, #f3f6f4 0%, #eaf0ec 100%);
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

.portrait-btn-more {
  width: 100%;
  height: 60rpx;
  border-radius: 14rpx;
  background: var(--app-color-surface-soft, #f3f6f4);
  color: #4c5d56;
  font-size: 23rpx;
}
</style>
