<template>
  <view class="page-container">
    <!-- 自定义导航栏 -->
    <view class="nav-bar">
      <text class="nav-title">角色人设</text>
    </view>

    <!-- 角色设定列表 -->
    <scroll-view scroll-y class="character-scroll">
      <view class="character-list">
        <view 
          class="character-card" 
          v-for="char in personaStore.characterList" 
          :key="char.id"
          @tap="goToDetail(char)"
          @longpress="onCharacterLongPress(char)"
          @contextmenu.prevent="onCharacterLongPress(char)"
        >
          <image class="char-avatar" :src="getAvatarUrl(char.avatar_path || '') || '/static/default-avatar.png'" mode="aspectFill" />
          <view class="char-info">
            <text class="char-name">{{ char.name }}</text>
            <text class="char-desc">{{ char.description }}</text>
          </view>
        </view>

        <!-- 角色空状态 -->
        <view v-if="personaStore.characterList.length === 0" class="empty-state">
          <text class="empty-text">暂无角色，点击消息页右上角创建</text>
        </view>
      </view>
    </scroll-view>

    <!-- 自定义底部导航栏 -->
    <TabBar activeTab="character" />
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { usePersonaStore } from "@/store/personaStore";
import TabBar from "@/components/common/TabBar.vue";
import { getAvatarUrl } from "@/api/characters";

const personaStore = usePersonaStore();

onShow(() => {
  uni.hideTabBar({ animation: false });
  personaStore.loadCharacters();
});

const goToDetail = (char: any) => {
  uni.navigateTo({
    url: `/pages/character/detail?id=${char.id}`
  });
};

const onCharacterLongPress = (char: any) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ['编辑人设', '删除角色'],
    success: (res) => {
      if (res.tapIndex === 0) {
        uni.navigateTo({
          url: `/pages/character/create?id=${char.id}`
        });
      } else if (res.tapIndex === 1) {
        uni.showModal({
          title: '删除角色',
          content: `确定要删除"${char.name}"吗？此角色关联的所有会话故事及记忆都将无法找回。`,
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (modalRes) => {
            if (modalRes.confirm) {
              try {
                uni.showLoading({ title: '正在删除...' });
                await personaStore.removeCharacterFromList(char.id);
                uni.hideLoading();
                uni.showToast({ title: '角色已删除', icon: 'success' });
              } catch (e) {
                uni.hideLoading();
                uni.showToast({ title: '删除失败，请重试', icon: 'none' });
                console.error('Failed to delete character', e);
              }
            }
          }
        });
      }
    }
  });
};
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100%;
  background-color: #fafafa;
}

/* ===== 自定义导航栏 ===== */
.nav-bar {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  display: flex;
  align-items: center;
  background-color: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.nav-title {
  font-size: 34rpx;
  font-weight: 600;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

/* ===== 角色列表样式 ===== */
.character-scroll {
  flex: 1;
  height: 0;
  min-height: 0;
}

.character-list {
  padding: 28rpx 36rpx 180rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.character-card {
  display: flex;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 28rpx 24rpx;
  align-items: center;
  gap: 24rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
}

.character-card:active {
  transform: scale(0.975);
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.char-avatar {
  width: 104rpx;
  height: 104rpx;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.char-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.char-name {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
  margin-bottom: 6rpx;
}

.char-desc {
  font-size: 26rpx;
  color: #8e8e93;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty-state {
  padding: 180rpx 0;
  display: flex;
  justify-content: center;
  text-align: center;
}

.empty-text {
  font-size: 28rpx;
  color: #8e8e93;
}
</style>
