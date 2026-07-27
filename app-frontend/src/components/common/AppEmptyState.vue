<template>
  <view class="app-empty-state">
    <view class="empty-visual" aria-hidden="true">
      <slot name="visual">
        <view class="card-outline card-back"></view>
        <view class="card-outline card-front">
          <view class="portrait-mark"></view>
          <view class="story-line story-line-long"></view>
          <view class="story-line story-line-short"></view>
        </view>
      </slot>
    </view>

    <view class="empty-copy">
      <text v-if="eyebrow" class="empty-eyebrow">{{ eyebrow }}</text>
      <text class="empty-title">{{ title }}</text>
      <text v-if="description" class="empty-description">{{ description }}</text>
    </view>

    <view v-if="$slots.actions" class="empty-actions">
      <slot name="actions"></slot>
    </view>
  </view>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    eyebrow?: string;
  }>(),
  {
    description: "",
    eyebrow: "",
  }
);
</script>

<style scoped>
.app-empty-state {
  display: flex;
  width: 100%;
  max-width: 600rpx;
  margin: 0 auto;
  padding: 112rpx var(--app-page-gutter, 36rpx) 80rpx;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.empty-visual {
  position: relative;
  width: 184rpx;
  height: 168rpx;
  margin-bottom: 36rpx;
}

.card-outline {
  position: absolute;
  width: 128rpx;
  height: 160rpx;
  border: 2rpx solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 26rpx;
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
}

.card-back {
  top: 0;
  left: 16rpx;
  background-color: rgba(139, 184, 220, 0.11);
  transform: rotate(-8deg);
}

.card-front {
  right: 8rpx;
  bottom: 0;
  display: flex;
  padding: 20rpx;
  flex-direction: column;
  align-items: center;
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
  transform: rotate(6deg);
}

.portrait-mark {
  width: 54rpx;
  height: 54rpx;
  margin-bottom: 16rpx;
  border-radius: 50%;
  background: linear-gradient(145deg, rgba(112, 174, 155, 0.28), rgba(139, 184, 220, 0.22));
}

.story-line {
  height: 8rpx;
  margin-top: 9rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.story-line-long {
  width: 76rpx;
}

.story-line-short {
  width: 48rpx;
}

.empty-copy {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10rpx;
}

.empty-eyebrow {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 650;
  letter-spacing: 2rpx;
}

.empty-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-title-sm, 32rpx);
  font-weight: 680;
  line-height: 1.35;
}

.empty-description {
  max-width: 500rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  line-height: 1.65;
}

.empty-actions {
  display: flex;
  width: 100%;
  margin-top: 36rpx;
  justify-content: center;
}
</style>
