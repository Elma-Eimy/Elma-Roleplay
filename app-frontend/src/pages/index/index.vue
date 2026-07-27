<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 自定义导航栏 -->
    <view class="nav-bar">
      <text class="nav-title">消息会话</text>
      
      <!-- 顶部加号功能菜单按钮 -->
      <view class="plus-btn" :class="{ 'is-active': isMenuOpen }" @tap="toggleMenu">
        <image class="plus-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
      </view>

      <!-- 下拉快捷操作菜单 -->
      <view v-if="isMenuOpen" class="dropdown-menu">
        <view class="menu-item" @tap="handleMenuAction('create_session')">
          <image class="menu-icon" src="/static/icons/menu_chat.svg" mode="aspectFit" />
          <text class="menu-text">发起新对话</text>
        </view>
        <view class="menu-divider"></view>
        <view class="menu-item" @tap="handleMenuAction('add_character')">
          <image class="menu-icon" src="/static/icons/menu_user_plus.svg" mode="aspectFit" />
          <text class="menu-text">创建新角色</text>
        </view>
      </view>
      <!-- 点击关闭下拉菜单的背景遮罩 -->
      <view v-if="isMenuOpen" class="menu-backdrop" @tap="isMenuOpen = false"></view>
    </view>

    <!-- 最近会话列表滚动容器 -->
    <scroll-view scroll-y class="session-scroll">
      <view class="session-list">
        <view 
          class="session-item" 
          v-for="session in sessions" 
          :key="session.id"
          @tap="goToChat(session)"
          @longpress="onSessionLongPress(session)"
          @contextmenu.prevent="onSessionLongPress(session)"
        >
          <image class="session-avatar" :src="getAvatarUrl(session.characterAvatar || '') || '/static/default-avatar.png'" mode="aspectFill" />
          
          <view class="session-content">
            <view class="session-header">
              <text class="session-title">{{ session.title || session.characterName }}</text>
              <text class="session-time">{{ formatDate(session.updated_at) }}</text>
            </view>
            <view class="session-footer">
              <text class="session-preview">{{ session.lastMessage || '开启新的聊天...' }}</text>
              <view v-if="session.unread" class="unread-dot"></view>
            </view>
          </view>
        </view>

        <!-- 暂无会话消息空状态 -->
        <view v-if="sessions.length === 0" class="empty-state">
          <text class="empty-text">暂无对话消息</text>
        </view>
      </view>
    </scroll-view>

    <!-- 开启新故事会话模态框 -->
    <NewSessionModal 
      v-model:isOpen="isNewSessionModalOpen" 
      @confirm="startNewSession"
    />

    <!-- 重命名会话模态框 -->
    <view v-if="renamingSessionId !== null" class="rename-modal-backdrop">
      <view class="rename-modal">
        <text class="modal-title">重命名会话</text>
        <input class="rename-input" v-model="newSessionTitle" placeholder="请输入新会话名称..." :focus="true" />
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="cancelRename">取消</view>
          <view class="modal-btn save" @tap="saveRename">保存</view>
        </view>
      </view>
    </view>
    <!-- 自定义底部导航栏 -->
    <TabBar activeTab="index" />
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { usePersonaStore } from "@/store/personaStore";
import { getSessions, getSessionHistory, updateSessionTitle, deleteSession } from "@/api/sessions";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import TabBar from "@/components/common/TabBar.vue";
import { getAvatarUrl } from "@/api/characters";

const personaStore = usePersonaStore();
const isMenuOpen = ref(false);
const isNewSessionModalOpen = ref(false);

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");

const sessions = ref<any[]>([]);
const isLoading = ref(false);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

const loadRecentSessions = async () => {
  isLoading.value = true;
  try {
    // 1. 确保已加载角色设定列表
    await personaStore.loadCharacters();

    // 2. 拉取所有已创建角色的分支会话
    const allSessions: any[] = [];
    const promises = personaStore.characterList.map(async (char) => {
      try {
        const res = await getSessions(char.id);
        const decorated = res.sessions.map((s) => ({
          ...s,
          characterName: char.name,
          characterAvatar: char.avatar_path,
          lastMessage: "",
          unread: false
        }));
        allSessions.push(...decorated);
      } catch (err) {
        console.error(`Failed to load sessions for character ${char.id}`, err);
      }
    });
    await Promise.all(promises);

    // 3. 获取每个分支会话的最后一条消息内容，并对换行符和空白字符进行空格替换清洗
    const historyPromises = allSessions.map(async (s) => {
      try {
        const hRes = await getSessionHistory(s.id, 1);
        if (hRes.messages.length > 0) {
          const lastMsg = hRes.messages[hRes.messages.length - 1];
          const rawMsg = lastMsg.content;
          s.lastMessage = rawMsg ? rawMsg.replace(/\s+/g, " ").trim() : "";
          s.lastMessageTime = lastMsg.created_at || s.updated_at;
        } else {
          s.lastMessage = "开启新的聊天...";
          s.lastMessageTime = s.updated_at;
        }
      } catch (err) {
        s.lastMessage = "开启新的聊天...";
        s.lastMessageTime = s.updated_at;
      }
    });
    await Promise.all(historyPromises);

    // 4. 按最近消息发送时间进行倒序排列
    allSessions.sort((a, b) => new Date(b.lastMessageTime).getTime() - new Date(a.lastMessageTime).getTime());
    sessions.value = allSessions;
  } catch (e) {
    console.error("Failed to load recent sessions", e);
  } finally {
    isLoading.value = false;
  }
};

onShow(() => {
  uni.hideTabBar({ animation: false });
  loadRecentSessions();
});

const toggleMenu = () => {
  isMenuOpen.value = !isMenuOpen.value;
};

const handleMenuAction = (action: string) => {
  isMenuOpen.value = false;
  
  if (action === 'create_session') {
    uni.switchTab({
      url: '/pages/character/index'
    });
  } else if (action === 'add_character') {
    uni.navigateTo({
      url: '/pages/character/create'
    });
  }
};

const goToChat = (session: any) => {
  uni.navigateTo({
    url: `/pages/chat/chat?sessionId=${session.id}`
  });
};

const onSessionLongPress = (session: any) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ['重命名', '删除会话'],
    success: (res) => {
      if (res.tapIndex === 0) {
        renamingSessionId.value = session.id;
        newSessionTitle.value = session.title || session.characterName;
      } else if (res.tapIndex === 1) {
        uni.showModal({
          title: '删除会话',
          content: '确定要删除此会话吗？所有聊天记录与记忆数据将无法找回。',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm) {
              try {
                await deleteSession(session.id);
                await loadRecentSessions();
                uni.showToast({ title: '删除成功', icon: 'success' });
              } catch (e: any) {
                console.error("Failed to delete session", e);
                uni.showToast({ title: e.message || '删除失败，请检查网络与后端配置', icon: 'none', duration: 3000 });
              }
            }
          }
        });
      }
    }
  });
};

const cancelRename = () => {
  renamingSessionId.value = null;
  newSessionTitle.value = "";
};

const saveRename = async () => {
  if (renamingSessionId.value !== null && newSessionTitle.value.trim() !== "") {
    try {
      await updateSessionTitle(renamingSessionId.value, newSessionTitle.value.trim());
      cancelRename();
      await loadRecentSessions();
    } catch (e) {
      console.error("Failed to update session title", e);
    }
  }
};

const startNewSession = (payload: { title: string; greeting_index: number | null }) => {
  uni.navigateTo({
    url: `/pages/chat/chat?title=${encodeURIComponent(payload.title)}`
  });
};

const formatDate = (dateString: string) => {
  if (!dateString) return "";
  const date = new Date(dateString);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
};
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  background-color: #fafafa;
  overflow: hidden;
}

/* ===== 自定义导航栏 ===== */
.nav-bar {
  position: relative;
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.nav-title {
  font-size: 34rpx;
  font-weight: 600;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

.plus-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.03);
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.plus-btn:active {
  background-color: rgba(0, 0, 0, 0.08);
  transform: scale(0.94);
}

.plus-btn.is-active {
  transform: rotate(45deg);
  background-color: rgba(0, 0, 0, 0.08);
}

.plus-icon {
  width: 32rpx;
  height: 32rpx;
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.menu-icon {
  width: 36rpx;
  height: 36rpx;
}

/* ===== 下拉快捷菜单 ===== */
.menu-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 40;
}

.dropdown-menu {
  position: absolute;
  top: calc(110rpx + env(safe-area-inset-top, 40rpx) + 8rpx);
  right: 28rpx;
  width: 280rpx;
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-radius: 20rpx;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  border: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 100;
  padding: 8rpx 0;
  animation: slideDown 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 20rpx 28rpx;
  gap: 16rpx;
  transition: background-color 0.2s;
}

.menu-item:active {
  background-color: rgba(0, 0, 0, 0.03);
}

.menu-icon {
  color: #1c1c1e;
}

.menu-text {
  font-size: 26rpx;
  color: #1c1c1e;
  font-weight: 500;
}

.menu-divider {
  height: 1px;
  background-color: rgba(0, 0, 0, 0.03);
  margin: 0 20rpx;
}

/* ===== 会话列表样式 ===== */
.session-scroll {
  flex: 1;
  /* H5 端：scroll-view 在 flex 容器内必须有明确高度才能滚动 */
  height: 0;
  min-height: 0;
  overflow: hidden;
}

.session-list {
  padding: 16rpx 0 180rpx 0;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 24rpx 36rpx;
  gap: 24rpx;
  background-color: transparent;
  transition: all 0.2s ease;
}

.session-item:active {
  background-color: rgba(0, 0, 0, 0.02);
  opacity: 0.95;
}

.session-avatar {
  width: 100rpx;
  height: 100rpx;
  border-radius: 32%;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.session-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
  padding-bottom: 24rpx;
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6rpx;
}

.session-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time {
  font-size: 22rpx;
  color: #8e8e93;
  flex-shrink: 0;
}

.session-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.session-preview {
  font-size: 26rpx;
  color: #8e8e93;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  padding-right: 16rpx;
  line-height: 1.4;
}

.unread-dot {
  width: 14rpx;
  height: 14rpx;
  background-color: #ff3b30;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ===== Empty State ===== */
.empty-state {
  padding: 180rpx 0;
  display: flex;
  justify-content: center;
}

.empty-text {
  font-size: 28rpx;
  color: #8e8e93;
  font-weight: 400;
}

/* ===== 重命名模态框 ===== */
.rename-modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.rename-modal {
  width: 580rpx;
  background-color: #ffffff;
  border-radius: 28rpx;
  padding: 44rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.modal-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  text-align: center;
}

.rename-input {
  width: 100%;
  height: 80rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  box-sizing: border-box;
}

.rename-input:focus {
  border-color: #1c1c1e;
  background-color: #ffffff;
}

.modal-actions {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
}

.modal-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: 600;
  transition: all 0.2s;
}

.modal-btn.cancel {
  background-color: rgba(0, 0, 0, 0.03);
  color: #48484a;
}

.modal-btn.cancel:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.modal-btn.save {
  background-color: #1c1c1e;
  color: #ffffff;
}

.modal-btn.save:active {
  background-color: #000000;
  transform: scale(0.97);
}

/* Android Performance Fallbacks (Disable Frosted Glass) */
.is-android .nav-bar {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02) !important;
}

.is-android .dropdown-menu {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12) !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
}

.is-android .rename-modal-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.5) !important;
}
</style>
