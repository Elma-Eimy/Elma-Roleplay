<template>
  <view
    class="input-area-wrapper"
    :class="{ 'is-android': isAndroid }"
    :style="wrapperStyle"
  >
    <view class="reasoning-toggle-row">
      <view
        class="reasoning-toggle-btn"
        :class="{ 'is-reasoning': useReasoning }"
        @tap="emit('update:useReasoning', !useReasoning)"
      >
        <image
          class="reasoning-icon"
          :src="
            useReasoning
              ? '/static/icons/chat_sparkle_active.svg'
              : '/static/icons/chat_sparkle.svg'
          "
          mode="aspectFit"
        />
        <text class="reasoning-label">
          {{ useReasoning ? "深度思考" : "思考" }}
        </text>
      </view>
    </view>

    <view class="input-area" :class="{ 'is-focused': isFocused }">
      <textarea
        class="chat-input"
        :value="modelValue"
        placeholder="写下接下来的故事…"
        :auto-height="true"
        :maxlength="-1"
        :adjust-position="false"
        :cursor-spacing="0"
        :confirm-hold="true"
        confirm-type="send"
        @input="handleInput"
        @confirm="emit('send')"
        @focus="emit('focus-change', true)"
        @blur="emit('focus-change', false)"
        @linechange="emit('line-change')"
      />
      <view
        class="send-btn"
        :class="{ 'is-active': modelValue.trim().length > 0 }"
        @tap="emit('send')"
      >
        <image
          class="send-icon"
          src="/static/icons/chat_send.svg"
          mode="aspectFit"
        />
      </view>
    </view>

    <view
      class="keyboard-spacer"
      :style="{ height: `${keyboardHeight}px` }"
    ></view>
  </view>
</template>

<script setup lang="ts">
import type { CSSProperties } from "vue";

defineProps<{
  modelValue: string;
  useReasoning: boolean;
  isFocused: boolean;
  isAndroid: boolean;
  keyboardHeight: number;
  wrapperStyle: CSSProperties;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "update:useReasoning", value: boolean): void;
  (event: "focus-change", focused: boolean): void;
  (event: "line-change"): void;
  (event: "send"): void;
}>();

const handleInput = (event: Event) => {
  const inputEvent = event as unknown as { detail: { value: string } };
  emit("update:modelValue", inputEvent.detail.value);
};
</script>

<style scoped>
.input-area-wrapper {
  position: relative;
  z-index: 10;
  padding:
    10rpx
    28rpx
    calc(env(safe-area-inset-bottom, 16rpx) + 18rpx);
  background: linear-gradient(
    180deg,
    rgba(247, 249, 247, 0) 0%,
    rgba(247, 249, 247, 0.88) 20%,
    rgba(247, 249, 247, 0.98) 100%
  );
}

.input-area-wrapper.is-android {
  background: linear-gradient(
    180deg,
    rgba(247, 249, 247, 0) 0%,
    #f7f9f7 24%
  );
}

.reasoning-toggle-row {
  display: flex;
  align-items: center;
  margin-bottom: 8rpx;
  padding-left: 10rpx;
}

.reasoning-toggle-btn {
  display: inline-flex;
  align-items: center;
  min-height: 46rpx;
  gap: 7rpx;
  padding: 0 16rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  background-color: rgba(255, 255, 255, 0.56);
  transition:
    transform var(--app-motion-normal, 0.25s) cubic-bezier(0.16, 1, 0.3, 1),
    background-color var(--app-motion-normal, 0.25s),
    border-color var(--app-motion-normal, 0.25s);
}

.reasoning-toggle-btn:active {
  transform: scale(0.95);
}

.reasoning-toggle-btn.is-reasoning {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  border-color: rgba(112, 174, 155, 0.2);
}

.reasoning-icon {
  width: 24rpx;
  height: 24rpx;
  flex-shrink: 0;
}

.reasoning-label {
  font-size: 21rpx;
  font-weight: 600;
  color: var(--app-color-text-secondary, #7c8983);
  line-height: 1;
}

.reasoning-toggle-btn.is-reasoning .reasoning-label {
  color: var(--app-color-primary-strong, #4f8e7c);
}

.input-area {
  display: flex;
  align-items: flex-end;
  padding: 7rpx 7rpx 7rpx 26rpx;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 34rpx;
  background-color: rgba(255, 255, 255, 0.92);
  box-shadow:
    0 16rpx 42rpx rgba(45, 72, 62, 0.13),
    inset 0 0 0 1px var(--app-color-border, rgba(38, 51, 46, 0.08));
  transition:
    background-color var(--app-motion-normal, 0.25s),
    border-color var(--app-motion-normal, 0.25s),
    box-shadow var(--app-motion-normal, 0.25s);
}

.input-area.is-focused {
  background-color: var(--app-color-surface, #ffffff);
  border-color: rgba(112, 174, 155, 0.28);
  box-shadow:
    0 18rpx 46rpx rgba(45, 72, 62, 0.15),
    0 0 0 4rpx rgba(112, 174, 155, 0.08);
}

.chat-input {
  flex: 1;
  min-height: 48rpx;
  max-height: 200rpx;
  padding: 14rpx 0;
  font-size: 28rpx;
  color: var(--app-color-text-primary, #26332e);
  line-height: 1.5;
  height: auto;
  overflow-y: auto !important;
}

.send-btn {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background-color: rgba(124, 137, 131, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-left: 16rpx;
  transition:
    transform var(--app-motion-normal, 0.25s) cubic-bezier(0.16, 1, 0.3, 1),
    background-color var(--app-motion-normal, 0.25s);
}

.send-btn.is-active {
  background-color: var(--app-color-primary, #70ae9b);
  box-shadow: 0 8rpx 20rpx rgba(79, 142, 124, 0.24);
}

.send-btn.is-active:active {
  transform: scale(0.92);
  background-color: var(--app-color-primary-strong, #4f8e7c);
}

.send-btn.is-active .send-icon {
  filter: brightness(0) invert(1);
}

.send-icon {
  width: 36rpx;
  height: 36rpx;
}

.keyboard-spacer {
  transition: height 0.1s ease-out;
}
</style>
