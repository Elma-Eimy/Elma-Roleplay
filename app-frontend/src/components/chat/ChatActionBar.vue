<template>
  <view
    v-if="items.length"
    class="chat-action-bar"
    @longpress.stop=""
    @contextmenu.prevent.stop=""
  >
    <view
      v-for="item in items"
      :key="item.key"
      class="action-bar-btn"
      :class="{
        'is-disabled': item.disabled,
        'is-playing': item.active,
        'is-danger': item.danger,
      }"
      role="button"
      :aria-disabled="item.disabled"
      @tap.stop="!item.disabled && emit('select', item.key)"
    >
      <view v-if="item.waveform" class="waveform">
        <view class="wave-bar bar-1"></view>
        <view class="wave-bar bar-2"></view>
        <view class="wave-bar bar-3"></view>
      </view>
      <text v-else-if="item.isMore" class="action-bar-more">···</text>
      <image
        v-else-if="item.icon"
        class="action-bar-icon"
        :class="{ 'tts-icon': item.key === 'tts' }"
        :src="item.icon"
        mode="aspectFit"
      />
      <text class="action-bar-label">{{ item.label }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
export interface ChatActionBarItem {
  key: string;
  label: string;
  icon?: string;
  isMore?: boolean;
  waveform?: boolean;
  active?: boolean;
  disabled?: boolean;
  danger?: boolean;
}

defineProps<{
  items: ChatActionBarItem[];
}>();

const emit = defineEmits<{
  (event: "select", key: string): void;
}>();
</script>

<style scoped>
.chat-action-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8rpx;
  margin-top: 10rpx;
  margin-left: 6rpx;
}

.action-bar-btn {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  min-height: 48rpx;
  padding: 0 18rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.64));
  color: var(--app-color-text-secondary, #64716b);
  transition:
    transform var(--app-motion-fast, 160ms) ease,
    background-color var(--app-motion-fast, 160ms) ease;
}

.action-bar-btn:active {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  transform: scale(0.95);
}

.action-bar-btn.is-disabled {
  opacity: 0.45;
}

.action-bar-btn.is-playing {
  color: var(--app-color-primary-strong, #4f8e7c);
  border-color: rgba(112, 174, 155, 0.2);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.action-bar-btn.is-danger {
  color: var(--app-color-danger, #d9655d);
}

.action-bar-icon {
  width: 22rpx;
  height: 22rpx;
  flex-shrink: 0;
  opacity: 0.78;
}

.action-bar-more {
  font-size: 24rpx;
  font-weight: 700;
  line-height: 1;
}

.action-bar-label {
  font-size: 21rpx;
  font-weight: 560;
}

.waveform {
  display: flex;
  align-items: flex-end;
  gap: 3rpx;
  width: 20rpx;
  height: 20rpx;
}

.wave-bar {
  width: 3rpx;
  height: 6rpx;
  background-color: var(--app-color-primary, #70ae9b);
  border-radius: 2rpx;
  animation: bounce 0.8s ease-in-out infinite alternate;
}

.wave-bar.bar-1 {
  animation-delay: 0.1s;
}

.wave-bar.bar-2 {
  animation-delay: 0.3s;
  height: 12rpx;
}

.wave-bar.bar-3 {
  animation-delay: 0.5s;
}

@keyframes bounce {
  from { height: 6rpx; }
  to { height: 18rpx; }
}
</style>
