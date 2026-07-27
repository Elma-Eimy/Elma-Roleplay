<template>
  <view class="page-container app-motion-enter" :class="{ 'is-android': isAndroid }">
    <AppSoftGlow />

    <AppPageHeader
      title="故事"
      eyebrow="STORIES"
      subtitle="继续一段未完的相遇"
    >
      <template #action>
        <view
          class="plus-btn app-icon-button"
          :class="{ 'is-active': isMenuOpen }"
          role="button"
          aria-label="新建"
          @tap="toggleMenu"
        >
          <image class="plus-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
        </view>

        <view v-if="isMenuOpen" class="dropdown-menu">
          <view class="menu-item" @tap="handleMenuAction('create_session')">
            <image class="menu-icon" src="/static/icons/menu_chat.svg" mode="aspectFit" />
            <text class="menu-text">开启新故事</text>
          </view>
          <view class="menu-divider"></view>
          <view class="menu-item" @tap="handleMenuAction('add_character')">
            <image class="menu-icon" src="/static/icons/menu_user_plus.svg" mode="aspectFit" />
            <text class="menu-text">创建新角色</text>
          </view>
        </view>

        <view v-if="isMenuOpen" class="menu-backdrop" @tap="isMenuOpen = false"></view>
      </template>
    </AppPageHeader>

    <scroll-view scroll-y class="home-scroll">
      <view class="home-content">
        <view v-if="isHomeLoading && !hasHomeContent" class="home-skeleton">
          <view class="skeleton-feature"></view>
          <view class="skeleton-heading"></view>
          <view class="skeleton-characters">
            <view v-for="index in 4" :key="index" class="skeleton-character"></view>
          </view>
        </view>

        <template v-else-if="hasHomeContent">
          <view v-if="featuredSession" class="featured-section">
            <view class="section-kicker-row">
              <text class="section-kicker">继续故事</text>
              <text class="featured-time">
                {{ formatDate(featuredSession.lastMessageTime || featuredSession.updated_at) }}
              </text>
            </view>

            <view
              class="featured-card"
              @tap="goToChat(featuredSession)"
              @longpress="onSessionLongPress(featuredSession)"
              @contextmenu.prevent="onSessionLongPress(featuredSession)"
            >
              <AvatarImage
                class="featured-art"
                :src="getAvatarUrl(featuredSession.characterAvatar)"
                :lazy-load="false"
              />
              <view class="featured-image-wash"></view>
              <view class="featured-card-glow"></view>

              <view class="featured-copy">
                <view class="featured-character-row">
                  <view class="featured-status-dot"></view>
                  <text class="featured-character">{{ featuredSession.characterName }}</text>
                </view>
                <text class="featured-title">{{ getSessionTitle(featuredSession) }}</text>
                <text class="featured-preview">{{ getSessionPreview(featuredSession) }}</text>

                <view class="continue-button" @tap.stop="goToChat(featuredSession)">
                  <text class="continue-label">继续</text>
                  <text class="continue-arrow">→</text>
                </view>
              </view>
            </view>
          </view>

          <view v-else class="start-story-card">
            <view class="start-story-copy">
              <text class="start-story-kicker">从角色开始</text>
              <text class="start-story-title">挑选一位角色，写下新的篇章</text>
              <text class="start-story-description">你创建的角色会保留各自独立的故事线与记忆。</text>
            </view>
            <view class="start-story-action" @tap="goToCharacterLibrary">
              <text>选择角色</text>
              <text>→</text>
            </view>
          </view>

          <view v-if="quickCharacters.length > 0" class="characters-section">
            <view class="section-heading">
              <view class="section-heading-copy">
                <text class="section-title">我的角色</text>
                <text class="section-caption">从熟悉的面孔开启故事</text>
              </view>
              <view class="section-link" @tap="goToCharacterLibrary">
                <text>查看全部</text>
                <text class="section-link-arrow">›</text>
              </view>
            </view>

            <scroll-view scroll-x class="characters-scroll" :show-scrollbar="false">
              <view class="character-strip">
                <view
                  v-for="character in quickCharacters"
                  :key="character.id"
                  class="character-shortcut"
                  @tap="goToCharacter(character.id)"
                >
                  <view class="character-portrait-wrap">
                    <AvatarImage
                      class="character-portrait"
                      :src="getAvatarUrl(character.avatar_path)"
                    />
                    <view class="portrait-ring"></view>
                  </view>
                  <text class="character-name">{{ character.name || "未命名角色" }}</text>
                </view>

                <view class="character-shortcut add-character-shortcut" @tap="goToCreateCharacter">
                  <view class="character-portrait-wrap add-character-portrait">
                    <text class="add-character-plus">＋</text>
                  </view>
                  <text class="character-name add-character-label">新角色</text>
                </view>
              </view>
            </scroll-view>
          </view>

          <view v-if="recentSessions.length > 0" class="recent-section">
            <view class="section-heading recent-heading">
              <view class="section-heading-copy">
                <text class="section-title">最近故事</text>
                <text class="section-caption">每条故事线都保留自己的记忆</text>
              </view>
            </view>

            <view class="recent-story-list">
              <view
                v-for="session in recentSessions"
                :key="session.id"
                class="story-row"
                @tap="goToChat(session)"
                @longpress="onSessionLongPress(session)"
                @contextmenu.prevent="onSessionLongPress(session)"
              >
                <AvatarImage
                  class="story-avatar"
                  :src="getAvatarUrl(session.characterAvatar)"
                />

                <view class="story-copy">
                  <view class="story-meta-row">
                    <text class="story-character">{{ session.characterName }}</text>
                    <text class="story-time">
                      {{ formatDate(session.lastMessageTime || session.updated_at) }}
                    </text>
                  </view>
                  <text class="story-title">{{ getSessionTitle(session) }}</text>
                  <text class="story-preview">{{ getSessionPreview(session) }}</text>
                </view>

                <text class="story-chevron">›</text>
              </view>
            </view>
          </view>

          <view v-else-if="featuredSession" class="recent-prompt">
            <text class="recent-prompt-title">这里只有一条故事线</text>
            <text class="recent-prompt-copy">从角色画册选择另一位角色，开启不同的相遇。</text>
          </view>
        </template>

        <AppEmptyState
          v-else
          eyebrow="新的篇章"
          title="故事正在等待相遇"
          description="创建或导入一位角色，让第一段故事从这里开始。"
        >
          <template #actions>
            <view class="empty-actions-stack">
              <AppPrimaryButton label="创建角色" block @tap="goToCreateCharacter" />
              <view class="secondary-button" @tap="goToImportCharacter">
                <text class="secondary-button-label">导入角色卡</text>
              </view>
            </view>
          </template>
        </AppEmptyState>
      </view>
    </scroll-view>

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
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { usePersonaStore } from "@/store/personaStore";
import {
  getRecentSessions,
  getSessions,
  getSessionHistory,
  updateSessionTitle,
  deleteSession,
} from "@/api/sessions";
import type { RecentSessionSummary, SessionSummary } from "@/api/sessions";
import TabBar from "@/components/common/TabBar.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import AppEmptyState from "@/components/common/AppEmptyState.vue";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppPrimaryButton from "@/components/common/AppPrimaryButton.vue";
import AppSoftGlow from "@/components/common/AppSoftGlow.vue";
import { getAvatarUrl } from "@/api/characters";

interface HomeSession extends SessionSummary {
  characterName: string;
  characterAvatar: string;
  lastMessage: string;
  lastMessageTime: string;
  unread: boolean;
}

const personaStore = usePersonaStore();
const isMenuOpen = ref(false);

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");

const sessions = ref<HomeSession[]>([]);
const isLoading = ref(false);
const RECENT_SESSION_LIMIT = 50;
const QUICK_CHARACTER_LIMIT = 10;

const featuredSession = computed(() => sessions.value[0] || null);
const recentSessions = computed(() => sessions.value.slice(1));
const quickCharacters = computed(() =>
  personaStore.characterList.slice(0, QUICK_CHARACTER_LIMIT)
);
const isHomeLoading = computed(
  () => isLoading.value || personaStore.isLoadingCharacters
);
const hasHomeContent = computed(
  () => sessions.value.length > 0 || personaStore.characterList.length > 0
);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

const loadRecentSessions = async () => {
  isLoading.value = true;
  try {
    try {
      const response = await getRecentSessions(RECENT_SESSION_LIMIT);
      sessions.value = response.sessions
        .map(decorateRecentSession)
        .sort(
          (a, b) =>
            new Date(b.lastMessageTime).getTime() -
            new Date(a.lastMessageTime).getTime()
        );
      return;
    } catch (error) {
      // 仅在旧后端尚未提供聚合接口时回退，网络故障时避免制造更多请求。
      if (!isUnsupportedRecentSessionsEndpoint(error)) {
        throw error;
      }
      console.warn("Recent sessions endpoint is unavailable; using legacy requests.");
    }

    // 旧后端回退：复用首页已加载的角色列表，逐一读取其会话。
    const allSessions: HomeSession[] = [];
    const promises = personaStore.characterList.map(async (char) => {
      try {
        const res = await getSessions(char.id);
        const decorated = res.sessions.map((s) => ({
          ...s,
          characterName: char.name,
          characterAvatar: char.avatar_path,
          lastMessage: "",
          lastMessageTime: s.updated_at,
          unread: false
        }));
        allSessions.push(...decorated);
      } catch (err) {
        console.error(`Failed to load sessions for character ${char.id}`, err);
      }
    });
    await Promise.all(promises);

    // 获取每个分支会话的最后一条消息内容，并清洗换行与多余空白。
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

    // 按最近消息发送时间倒序排列。
    allSessions.sort((a, b) => new Date(b.lastMessageTime).getTime() - new Date(a.lastMessageTime).getTime());
    sessions.value = allSessions;
  } catch (e) {
    console.error("Failed to load recent sessions", e);
  } finally {
    isLoading.value = false;
  }
};

const loadHomeData = async () => {
  await personaStore.loadCharacters(QUICK_CHARACTER_LIMIT, 0);
  await loadRecentSessions();
};

const decorateRecentSession = (session: RecentSessionSummary): HomeSession => {
  const lastMessage = session.last_message;
  return {
    ...session,
    characterName: session.character.name,
    characterAvatar: session.character.avatar_path,
    lastMessage: lastMessage?.content
      ? lastMessage.content.replace(/\s+/g, " ").trim()
      : "开启新的聊天...",
    lastMessageTime: lastMessage?.created_at || session.updated_at,
    unread: false,
  };
};

const isUnsupportedRecentSessionsEndpoint = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  return /\[API Error (404|405|422)\]/.test(message);
};

onShow(() => {
  // #ifndef H5
  uni.hideTabBar({ animation: false });
  // #endif
  loadHomeData();
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

const goToChat = (session: HomeSession) => {
  uni.navigateTo({
    url: `/pages/chat/chat?sessionId=${session.id}`
  });
};

const goToCharacterLibrary = () => {
  uni.switchTab({
    url: "/pages/character/index"
  });
};

const goToCharacter = (characterId: number) => {
  uni.navigateTo({
    url: `/pages/character/detail?id=${characterId}`
  });
};

const goToCreateCharacter = () => {
  uni.navigateTo({
    url: "/pages/character/create"
  });
};

const goToImportCharacter = () => {
  uni.navigateTo({
    url: "/pages/character/create"
  });
};

const getSessionTitle = (session: HomeSession) =>
  session.title?.trim() || `${session.characterName || "角色"}的故事`;

const getSessionPreview = (session: HomeSession) =>
  session.lastMessage?.trim() || "故事还没有写下第一句话…";

const onSessionLongPress = (session: HomeSession) => {
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
          confirmColor: '#D9655D',
          cancelColor: '#7C8983',
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

const formatDate = (dateString: string) => {
  if (!dateString) return "";
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);

  if (diffMinutes >= 0 && diffMinutes < 1) return "刚刚";
  if (diffMinutes >= 1 && diffMinutes < 60) return `${diffMinutes} 分钟前`;

  const isToday = date.toDateString() === now.toDateString();
  if (isToday) {
    return `今天 ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "昨天";

  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
};
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  min-height: 100vh;
  min-height: 100dvh;
  background-color: var(--app-color-background, #f7f9f7);
  overflow: hidden;
}

/* ===== 顶部操作与菜单 ===== */
.plus-btn {
  width: 72rpx;
  height: 72rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  transition: transform var(--app-motion-normal, 240ms) cubic-bezier(0.16, 1, 0.3, 1);
}

.plus-btn:active {
  transform: scale(0.94);
}

.plus-btn.is-active {
  transform: rotate(45deg);
  background-color: rgba(112, 174, 155, 0.22);
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
  height: 100dvh;
  z-index: 40;
}

.dropdown-menu {
  position: absolute;
  top: calc(var(--app-header-height, 112rpx) + env(safe-area-inset-top, 40rpx));
  right: 28rpx;
  width: 280rpx;
  background-color: var(--app-color-surface-translucent, rgba(255, 255, 255, 0.88));
  backdrop-filter: blur(20px);
  border-radius: var(--app-radius-md, 24rpx);
  box-shadow: var(--app-shadow-raised, 0 20rpx 52rpx rgba(45, 72, 62, 0.12));
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
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
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.menu-icon {
  color: var(--app-color-text-primary, #26332e);
}

.menu-text {
  font-size: 26rpx;
  color: var(--app-color-text-primary, #26332e);
  font-weight: 500;
}

.menu-divider {
  height: 1px;
  background-color: var(--app-color-border, rgba(38, 51, 46, 0.08));
  margin: 0 20rpx;
}

/* ===== 首页滚动内容 ===== */
.home-scroll {
  position: relative;
  z-index: 1;
  flex: 1;
  height: 0;
  min-height: 0;
  overflow: hidden;
}

.home-content {
  padding: 28rpx var(--app-page-gutter, 36rpx) 196rpx;
}

.section-kicker-row,
.section-heading,
.story-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-kicker {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 700;
  letter-spacing: 1.2rpx;
}

.featured-time,
.story-time {
  color: var(--app-color-text-muted, #a4aea9);
  font-size: var(--app-font-size-caption, 22rpx);
}

.featured-card {
  position: relative;
  display: flex;
  height: 408rpx;
  margin-top: 18rpx;
  overflow: hidden;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-lg, 36rpx);
  background-color: var(--app-color-surface, #ffffff);
  box-shadow: var(--app-shadow-raised, 0 20rpx 52rpx rgba(45, 72, 62, 0.12));
  transition: transform var(--app-motion-fast, 160ms) ease;
}

.featured-card:active {
  transform: scale(0.986);
}

.featured-art {
  position: absolute;
  top: 0;
  right: 0;
  width: 64%;
  height: 100%;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.featured-image-wash {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(
      90deg,
      rgba(255, 255, 255, 1) 8%,
      rgba(255, 255, 255, 0.96) 34%,
      rgba(255, 255, 255, 0.48) 64%,
      rgba(255, 255, 255, 0.08) 100%
    ),
    linear-gradient(0deg, rgba(38, 51, 46, 0.18), rgba(38, 51, 46, 0) 58%);
}

.featured-card-glow {
  position: absolute;
  left: -80rpx;
  bottom: -120rpx;
  width: 340rpx;
  height: 300rpx;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    var(--app-color-primary-soft, rgba(112, 174, 155, 0.14)),
    rgba(112, 174, 155, 0) 70%
  );
}

.featured-copy {
  position: relative;
  z-index: 2;
  display: flex;
  width: 72%;
  height: 100%;
  padding: 40rpx 0 34rpx 36rpx;
  flex-direction: column;
}

.featured-character-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.featured-status-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
  box-shadow: 0 0 0 8rpx var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.featured-character {
  overflow: hidden;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.featured-title {
  display: -webkit-box;
  margin-top: 22rpx;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: 40rpx;
  font-weight: 720;
  line-height: 1.22;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.featured-preview {
  display: -webkit-box;
  margin-top: 14rpx;
  overflow: hidden;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.continue-button {
  display: inline-flex;
  min-width: 132rpx;
  height: 62rpx;
  margin-top: auto;
  padding: 0 22rpx;
  align-self: flex-start;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-primary, #70ae9b);
  box-shadow: 0 10rpx 24rpx rgba(79, 142, 124, 0.22);
}

.continue-label,
.continue-arrow {
  color: #ffffff;
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 700;
}

/* ===== 无会话但已有角色 ===== */
.start-story-card {
  display: flex;
  padding: 34rpx;
  align-items: flex-end;
  gap: 24rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-lg, 36rpx);
  background:
    radial-gradient(circle at 92% 12%, rgba(139, 184, 220, 0.18), transparent 42%),
    linear-gradient(140deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 242, 0.96));
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
}

.start-story-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.start-story-kicker {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 700;
}

.start-story-title {
  margin-top: 10rpx;
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-title-sm, 32rpx);
  font-weight: 700;
  line-height: 1.35;
}

.start-story-description {
  margin-top: 12rpx;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  line-height: 1.55;
}

.start-story-action {
  display: flex;
  height: 66rpx;
  padding: 0 22rpx;
  align-items: center;
  gap: 8rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-primary, #70ae9b);
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 650;
  white-space: nowrap;
}

/* ===== 我的角色 ===== */
.characters-section,
.recent-section {
  margin-top: 48rpx;
}

.section-heading-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4rpx;
}

.section-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-title-sm, 32rpx);
  font-weight: 700;
}

.section-caption {
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-caption, 22rpx);
}

.section-link {
  display: flex;
  min-height: 64rpx;
  padding-left: 20rpx;
  align-items: center;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 600;
}

.section-link-arrow {
  margin-left: 6rpx;
  font-size: 34rpx;
  line-height: 1;
}

.characters-scroll {
  width: calc(100% + var(--app-page-gutter, 36rpx));
  margin-top: 22rpx;
  white-space: nowrap;
}

.character-strip {
  display: inline-flex;
  padding-right: var(--app-page-gutter, 36rpx);
  gap: 22rpx;
}

.character-shortcut {
  display: inline-flex;
  width: 132rpx;
  flex-direction: column;
  align-items: center;
  vertical-align: top;
}

.character-portrait-wrap {
  position: relative;
  width: 128rpx;
  height: 154rpx;
}

.character-portrait {
  width: 128rpx;
  height: 154rpx;
  border-radius: 42rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
  box-shadow: var(--app-shadow-soft, 0 12rpx 36rpx rgba(45, 72, 62, 0.08));
}

.portrait-ring {
  position: absolute;
  inset: 0;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 42rpx;
  box-shadow: inset 0 0 0 1px var(--app-color-border, rgba(38, 51, 46, 0.08));
  pointer-events: none;
}

.character-name {
  display: block;
  width: 100%;
  margin-top: 14rpx;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-body-sm, 24rpx);
  font-weight: 600;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.add-character-portrait {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx dashed var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: 42rpx;
  background-color: rgba(255, 255, 255, 0.55);
}

.add-character-plus {
  color: var(--app-color-primary, #70ae9b);
  font-size: 54rpx;
  font-weight: 300;
}

.add-character-label {
  color: var(--app-color-text-secondary, #7c8983);
}

/* ===== 最近故事 ===== */
.recent-heading {
  margin-bottom: 20rpx;
}

.recent-story-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.story-row {
  display: flex;
  min-height: 142rpx;
  padding: 20rpx 18rpx;
  align-items: center;
  gap: 20rpx;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-md, 24rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
  transition:
    border-color var(--app-motion-fast, 160ms) ease,
    transform var(--app-motion-fast, 160ms) ease;
}

.story-row:active {
  border-color: var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  transform: scale(0.988);
}

.story-avatar {
  width: 94rpx;
  height: 110rpx;
  flex-shrink: 0;
  border-radius: 30rpx;
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.story-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.story-meta-row {
  gap: 12rpx;
}

.story-character {
  overflow: hidden;
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-caption, 22rpx);
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.story-time {
  flex-shrink: 0;
}

.story-title {
  margin-top: 6rpx;
  overflow: hidden;
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 680;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.story-preview {
  margin-top: 6rpx;
  overflow: hidden;
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.story-chevron {
  flex-shrink: 0;
  color: var(--app-color-text-muted, #a4aea9);
  font-size: 42rpx;
  font-weight: 300;
}

.recent-prompt {
  display: flex;
  margin-top: 42rpx;
  padding: 28rpx 30rpx;
  flex-direction: column;
  gap: 8rpx;
  border: 1px dashed var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: var(--app-radius-md, 24rpx);
  background-color: rgba(255, 255, 255, 0.48);
}

.recent-prompt-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 650;
}

.recent-prompt-copy {
  color: var(--app-color-text-secondary, #7c8983);
  font-size: var(--app-font-size-body-sm, 24rpx);
  line-height: 1.55;
}

/* ===== 首页空状态 ===== */
.empty-actions-stack {
  display: flex;
  width: 100%;
  max-width: 440rpx;
  flex-direction: column;
  gap: 16rpx;
}

.secondary-button {
  display: flex;
  width: 100%;
  height: var(--app-control-height, 88rpx);
  align-items: center;
  justify-content: center;
  border: 1px solid var(--app-color-border-strong, rgba(38, 51, 46, 0.14));
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-surface-soft, rgba(255, 255, 255, 0.78));
}

.secondary-button-label {
  color: var(--app-color-primary-strong, #4f8e7c);
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 650;
}

/* ===== 首屏加载骨架 ===== */
.home-skeleton {
  display: flex;
  flex-direction: column;
}

.skeleton-feature,
.skeleton-heading,
.skeleton-character {
  background: linear-gradient(
    100deg,
    rgba(255, 255, 255, 0.54) 10%,
    rgba(255, 255, 255, 0.96) 34%,
    rgba(255, 255, 255, 0.54) 58%
  );
  background-size: 220% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}

.skeleton-feature {
  height: 408rpx;
  border-radius: var(--app-radius-lg, 36rpx);
}

.skeleton-heading {
  width: 220rpx;
  height: 36rpx;
  margin-top: 48rpx;
  border-radius: var(--app-radius-pill, 999rpx);
}

.skeleton-characters {
  display: flex;
  margin-top: 24rpx;
  gap: 22rpx;
}

.skeleton-character {
  width: 128rpx;
  height: 154rpx;
  border-radius: 42rpx;
}

@keyframes skeleton-shimmer {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -120% 0;
  }
}

/* ===== 重命名模态框 ===== */
.rename-modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
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
