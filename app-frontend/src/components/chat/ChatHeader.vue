<template>
  <view
    class="custom-header"
    :class="{ 'is-android': isAndroid, 'is-faded': isFaded }"
  >
    <view class="header-btn left-btn" @tap="emit('back')">
      <image
        class="back-icon"
        src="/static/icons/header_back.svg"
        mode="aspectFit"
      />
    </view>

    <view class="header-center" @tap="emit('open-status')">
      <AvatarImage
        v-if="avatarUrl"
        class="header-avatar"
        :src="avatarUrl"
      />
      <view class="header-titles">
        <text class="character-name">{{ characterName || "未选角色" }}</text>
        <view class="status-indicator">
          <view class="status-dot"></view>
          <text class="status-text">{{ currentMood || "在线" }}</text>
          <template v-if="typeof affectionScore === 'number'">
            <text class="status-sep">·</text>
            <image
              class="header-heart-icon"
              src="/static/icons/meta_heart.svg"
              mode="aspectFit"
            />
            <text class="status-affection">{{ affectionScore }}</text>
          </template>
        </view>
      </view>
    </view>

    <view class="header-btn right-btn" @tap="emit('open-status')">
      <image
        class="info-icon"
        src="/static/icons/header_info.svg"
        mode="aspectFit"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import AvatarImage from "@/components/common/AvatarImage.vue";

defineProps<{
  characterName?: string;
  currentMood?: string;
  affectionScore?: number;
  avatarUrl?: string;
  isAndroid: boolean;
  isFaded?: boolean;
}>();

const emit = defineEmits<{
  (event: "back"): void;
  (event: "open-status"): void;
}>();
</script>

<style scoped>
.custom-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 108rpx);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: var(--app-page-gutter, 36rpx);
  padding-right: var(--app-page-gutter, 36rpx);
  background-color: rgba(250, 252, 250, 0.78);
  backdrop-filter: blur(24px);
  border-bottom: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  position: relative;
  z-index: 50;
  transition:
    opacity var(--app-motion-normal, 240ms) ease,
    transform var(--app-motion-normal, 240ms) ease;
}

.custom-header.is-faded {
  opacity: 0.18;
  transform: translateY(-8rpx);
}

.custom-header.is-android {
  backdrop-filter: none;
  background-color: #f9fbf9;
  border-bottom-color: var(--app-color-border, rgba(38, 51, 46, 0.08));
  box-shadow: 0 4rpx 18rpx rgba(45, 72, 62, 0.035);
}

.header-btn {
  width: 72rpx;
  height: 72rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  background-color: rgba(255, 255, 255, 0.62);
  transition:
    transform var(--app-motion-fast, 160ms) ease,
    background-color var(--app-motion-fast, 160ms) ease;
}

.header-btn:active {
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  transform: scale(0.94);
}

.left-btn {
  margin-left: -10rpx;
}

.right-btn {
  margin-right: -10rpx;
}

.header-center {
  display: flex;
  align-items: center;
  gap: 16rpx;
  min-width: 0;
}

.header-avatar {
  width: 56rpx;
  height: 56rpx;
  border-radius: 22rpx;
  border: 1px solid rgba(255, 255, 255, 0.72);
  flex-shrink: 0;
}

.header-titles {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4rpx;
  min-width: 0;
}

.character-name {
  max-width: 340rpx;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: 30rpx;
  font-weight: 680;
  letter-spacing: -0.3rpx;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  min-height: 36rpx;
  padding: 0 14rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.status-dot {
  width: 8rpx;
  height: 8rpx;
  background-color: var(--app-color-primary, #70ae9b);
  border-radius: 50%;
  box-shadow: 0 0 0 5rpx rgba(112, 174, 155, 0.1);
}

.status-text,
.status-affection {
  font-size: var(--app-font-size-caption, 22rpx);
  color: var(--app-color-primary-strong, #4f8e7c);
  font-weight: 600;
}

.status-sep {
  color: var(--app-color-text-muted, #89958f);
  font-size: 20rpx;
}

.header-heart-icon {
  width: 20rpx;
  height: 20rpx;
  flex-shrink: 0;
}

.back-icon {
  width: 44rpx;
  height: 44rpx;
}

.info-icon {
  width: 40rpx;
  height: 40rpx;
}
</style>
