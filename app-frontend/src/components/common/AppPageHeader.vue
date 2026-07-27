<template>
  <view class="app-page-header" :class="{ 'is-compact': compact }">
    <view class="header-leading">
      <view
        v-if="showBack"
        class="back-button app-icon-button"
        role="button"
        aria-label="返回"
        @tap="handleBack"
      >
        <image
          class="back-icon"
          src="/static/icons/header_back.svg"
          mode="aspectFit"
        />
      </view>
      <slot v-else name="leading"></slot>
    </view>

    <view class="header-copy">
      <text v-if="eyebrow" class="header-eyebrow">{{ eyebrow }}</text>
      <text class="header-title">{{ title }}</text>
      <text v-if="subtitle" class="header-subtitle">{{ subtitle }}</text>
    </view>

    <view class="header-action">
      <slot name="action"></slot>
    </view>
  </view>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    eyebrow?: string;
    subtitle?: string;
    showBack?: boolean;
    compact?: boolean;
  }>(),
  {
    eyebrow: "",
    subtitle: "",
    showBack: false,
    compact: false,
  }
);

const emit = defineEmits<{
  back: [];
}>();

const handleBack = () => {
  emit("back");
  uni.navigateBack();
};
</script>

<style scoped>
.app-page-header {
  position: relative;
  z-index: 50;
  display: grid;
  grid-template-columns: 88rpx minmax(0, 1fr) 88rpx;
  min-height: calc(env(safe-area-inset-top, 40rpx) + var(--app-header-height, 112rpx));
  padding:
    env(safe-area-inset-top, 40rpx)
    var(--app-page-gutter, 36rpx)
    20rpx;
  align-items: center;
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  background-color: var(--app-color-surface-translucent, rgba(255, 255, 255, 0.88));
  backdrop-filter: blur(24px);
}

.app-page-header.is-compact {
  padding-bottom: 12rpx;
}

.header-leading,
.header-action {
  display: flex;
  min-width: 0;
  align-items: center;
}

.header-action {
  justify-content: flex-end;
}

.header-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  gap: 2rpx;
  text-align: center;
}

.header-eyebrow {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 650;
  letter-spacing: 1.6rpx;
}

.header-title {
  max-width: 100%;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-title-sm, 32rpx);
  font-weight: 680;
  letter-spacing: -0.4rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-subtitle {
  max-width: 100%;
  overflow: hidden;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-caption, 22rpx);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.back-button {
  margin-left: -20rpx;
}

.back-icon {
  width: 40rpx;
  height: 40rpx;
}
</style>
