<template>
  <view
    v-if="isOpen"
    class="action-sheet-backdrop"
    :class="{ 'is-android': isAndroid }"
    @tap="emit('close')"
  >
    <view
      class="action-sheet"
      role="dialog"
      :aria-label="title || '操作菜单'"
      @tap.stop
    >
      <view class="sheet-handle"></view>
      <text v-if="title" class="sheet-title">{{ title }}</text>
      <view class="sheet-list">
        <view
          v-for="item in items"
          :key="item.key"
          class="sheet-item"
          :class="{ 'is-danger': item.danger }"
          @tap="emit('select', item.key)"
        >
          <image
            v-if="item.icon"
            class="sheet-item-icon"
            :class="{ 'is-danger': item.danger }"
            :src="item.icon"
            mode="aspectFit"
          />
          <text class="sheet-item-label">{{ item.label }}</text>
        </view>
      </view>
      <view class="sheet-cancel" @tap="emit('close')">
        <text class="sheet-cancel-text">取消</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
export interface ActionSheetItem {
  key: string;
  label: string;
  icon?: string;
  danger?: boolean;
}

defineProps<{
  isOpen: boolean;
  items: ReadonlyArray<ActionSheetItem>;
  title?: string;
  isAndroid?: boolean;
}>();

const emit = defineEmits<{
  (event: "select", key: string): void;
  (event: "close"): void;
}>();
</script>

<style scoped>
.action-sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  background-color: var(--app-color-mask, rgba(25, 37, 32, 0.42));
  backdrop-filter: blur(8px);
  animation: sheet-backdrop-fade var(--app-motion-fast, 160ms) ease both;
}

.action-sheet-backdrop.is-android {
  backdrop-filter: none;
  background-color: rgba(25, 37, 32, 0.54);
}

.action-sheet {
  width: 100%;
  max-width: 680px;
  margin: 0 auto;
  padding: 16rpx 28rpx calc(env(safe-area-inset-bottom, 16rpx) + 20rpx);
  border-radius: var(--app-radius-lg, 36rpx) var(--app-radius-lg, 36rpx) 0 0;
  background-color: var(--app-color-surface, #ffffff);
  box-shadow: var(--app-shadow-raised, 0 20rpx 52rpx rgba(45, 72, 62, 0.12));
  animation: sheet-slide-up var(--app-motion-normal, 240ms) cubic-bezier(0.16, 1, 0.3, 1) both;
}

.sheet-handle {
  width: 72rpx;
  height: 8rpx;
  margin: 6rpx auto 18rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
}

.sheet-title {
  display: block;
  margin-bottom: 14rpx;
  color: var(--app-color-text-muted, #89958f);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 600;
  text-align: center;
}

.sheet-list {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.sheet-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  min-height: var(--app-touch-target, 88rpx);
  padding: 0 28rpx;
  border-radius: var(--app-radius-md, 24rpx);
  background-color: var(--app-color-background, #f7f9f7);
  transition:
    background-color var(--app-motion-fast, 160ms) ease,
    transform var(--app-motion-fast, 160ms) ease;
}

.sheet-item:active {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  transform: scale(0.985);
}

.sheet-item.is-danger {
  background-color: rgba(217, 101, 93, 0.06);
}

.sheet-item.is-danger:active {
  background-color: rgba(217, 101, 93, 0.14);
}

.sheet-item-icon {
  width: 34rpx;
  height: 34rpx;
  flex-shrink: 0;
  opacity: 0.78;
}

.sheet-item-icon.is-danger {
  opacity: 0.9;
}

.sheet-item-label {
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 560;
}

.sheet-item.is-danger .sheet-item-label {
  color: var(--app-color-danger, #d9655d);
  font-weight: 620;
}

.sheet-cancel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--app-touch-target, 88rpx);
  margin-top: 16rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-md, 24rpx);
  background-color: var(--app-color-surface, #ffffff);
}

.sheet-cancel:active {
  background-color: var(--app-color-background, #f7f9f7);
}

.sheet-cancel-text {
  color: var(--app-color-text-secondary, #64716b);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 600;
}

@keyframes sheet-backdrop-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes sheet-slide-up {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}
</style>
