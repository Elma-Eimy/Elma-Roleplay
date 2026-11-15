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
      <view class="home-content" :class="{ 'has-recent-stories': recentSessions.length > 0 }">
        <view class="group-entry" role="button" aria-label="查看与创建群聊故事" @tap="goToGroups">
          <view><text class="group-entry-title">群聊故事</text><text class="group-entry-copy">邀请几位角色，在同一场景相遇</text></view>
          <text class="group-entry-link">查看与创建 ›</text>
        </view>
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
                v-if="featuredSession.characterAvatar"
                class="featured-art"
                :src="getAvatarUrl(featuredSession.characterAvatar)"
                :lazy-load="false"
              />
              <view class="featured-image-wash"></view>
              <view class="featured-cover-label">未完 · 待续</view>

              <view class="featured-copy">
                <view class="featured-character-row">
                  <view class="featured-status-dot"></view>
                  <text class="featured-character">{{ featuredSession.characterName }}</text>
                </view>
                <text class="featured-title">{{ getSessionTitle(featuredSession) }}</text>
                <text class="featured-preview">{{ getSessionPreview(featuredSession) }}</text>

                <view class="continue-button" @tap.stop="goToChat(featuredSession)">
                  <text class="continue-label">继续这段故事</text>
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
                <text class="section-caption">每一次相遇，都有新的可能</text>
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
                  :class="{ 'has-portrait': !!character.avatar_path }"
                  role="button"
                  :aria-label="`查看${character.name || '未命名角色'}的档案`"
                  @tap="goToCharacter(character.id)"
                >
                  <view class="character-portrait-wrap">
                    <AvatarImage
                      v-if="character.avatar_path"
                      class="character-portrait"
                      :src="getAvatarUrl(character.avatar_path)"
                    />
                    <text v-else class="character-initial">{{ (character.name || '角色').slice(0, 1) }}</text>
                    <view class="portrait-shade"></view>
                  </view>
                  <view class="character-card-copy">
                    <text class="character-name">{{ character.name || "未命名角色" }}</text>
                    <text class="character-card-link">人物档案 ↗</text>
                  </view>
                </view>

                <view class="character-shortcut add-character-shortcut" @tap="goToCreateCharacter">
                  <view class="character-portrait-wrap add-character-portrait">
                    <text class="add-character-plus">＋</text>
                  </view>
                  <text class="character-name add-character-label">新角色</text>
                  <text class="add-character-hint">开启另一段相遇</text>
                </view>
              </view>
            </scroll-view>
          </view>

          <view v-if="recentSessions.length > 0" class="recent-section">
            <view class="section-heading recent-heading">
              <view class="section-heading-copy">
                <text class="section-title">最近故事</text>
                <text class="section-caption">翻开其他未完的篇章</text>
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
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { computed, ref } from "vue";
import { onShow } from "@dcloudio/uni-app";
import { usePersonaStore } from "@/store/personaStore";
import {
  getRecentSessions,
  getAllSessions,
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
        const res = await getAllSessions(char.id);
        const decorated = res.sessions.map((s) => ({
          ...s,
          characterName: char.name,
          characterAvatar: char.avatar_path,
          lastMessage: s.last_message?.content
            ? s.last_message.content.replace(/\s+/g, " ").trim()
            : "开启新的聊天...",
          lastMessageTime: s.last_message?.created_at || s.updated_at,
          unread: false
        }));
        allSessions.push(...decorated);
      } catch (err) {
        console.error(`Failed to load sessions for character ${char.id}`, err);
      }
    });
    await Promise.all(promises);

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

const goToGroups = () => uni.navigateTo({ url: "/pages/group/index" });

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
    url: "/pages/character/create?import=1"
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
                useChatSettingsStore().removeSession(session.id);
                await loadRecentSessions();
                uni.showToast({ title: '删除成功', icon: 'success' });
              } catch (e: unknown) {
                console.error("Failed to delete session", e);
                const errMessage = e instanceof Error ? e.message : "删除失败，请检查网络与后端配置";
                uni.showToast({ title: errMessage || '删除失败，请检查网络与后端配置', icon: 'none', duration: 3000 });
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
@import "./index.css";
</style>
