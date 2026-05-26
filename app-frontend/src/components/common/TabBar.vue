<template>
  <view class="tabbar-container">
    <view class="tabbar-panel">
      <!-- 标签页：会话列表 -->
      <view 
        class="tab-item" 
        :class="{ 'is-active': activeTab === 'index' }" 
        @tap="switchTab('/pages/index/index')"
      >
        <image 
          class="tab-icon" 
          style="width: 52rpx; height: 52rpx;"
          :src="activeTab === 'index' ? '/static/icons/tab_session_active.svg' : '/static/icons/tab_session.svg'" 
          mode="aspectFit"
        />
        <text class="tab-label">会话</text>
      </view>

      <!-- 标签页：角色列表 -->
      <view 
        class="tab-item" 
        :class="{ 'is-active': activeTab === 'character' }" 
        @tap="switchTab('/pages/character/index')"
      >
        <image 
          class="tab-icon" 
          style="width: 52rpx; height: 52rpx;"
          :src="activeTab === 'character' ? '/static/icons/tab_character_active.svg' : '/static/icons/tab_character.svg'" 
          mode="aspectFit"
        />
        <text class="tab-label">角色</text>
      </view>

      <!-- 标签页：设置 -->
      <view 
        class="tab-item" 
        :class="{ 'is-active': activeTab === 'settings' }" 
        @tap="switchTab('/pages/settings/index')"
      >
        <image 
          class="tab-icon" 
          style="width: 52rpx; height: 52rpx;"
          :src="activeTab === 'settings' ? '/static/icons/tab_settings_active.svg' : '/static/icons/tab_settings.svg'" 
          mode="aspectFit"
        />
        <text class="tab-label">设置</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  activeTab: 'index' | 'character' | 'settings';
}>();

const switchTab = (url: string) => {
  uni.switchTab({
    url,
    success: () => {
      uni.hideTabBar({ animation: false });
    }
  });
};
</script>

<style scoped>
.tabbar-container {
  position: fixed;
  bottom: calc(env(safe-area-inset-bottom, 24rpx) + 16rpx);
  left: 0;
  width: 100vw;
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 99;
  pointer-events: none;
}

.tabbar-panel {
  pointer-events: auto;
  display: flex;
  justify-content: space-around;
  align-items: center;
  width: 90vw;
  max-width: 600rpx;
  height: 110rpx;
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 55rpx;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  padding: 0 16rpx;
}

.tab-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  height: 100%;
  gap: 4rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  color: #8e8e93;
}

.tab-item:active {
  transform: scale(0.92);
}

.tab-item.is-active {
  color: #1c1c1e;
}

.tab-icon {
  width: 44rpx;
  height: 44rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.tab-item.is-active .tab-icon {
  transform: scale(1.1) translateY(-2rpx);
}

.tab-label {
  font-size: 20rpx;
  font-weight: 600;
  letter-spacing: 0.5px;
}
</style>
