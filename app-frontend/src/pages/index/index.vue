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
          <view class="menu-item" @tap="handleMenuAction('create_group')">
            <image class="menu-icon" src="/static/icons/menu_group.svg" mode="aspectFit" />
            <text class="menu-text">发起群聊</text>
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
      <view class="home-content" :class="{ 'has-recent-stories': recentStories.length > 0 }">
        <view v-if="isHomeLoading && !hasHomeContent" class="home-skeleton">
          <view class="skeleton-feature"></view>
          <view class="skeleton-heading"></view>
          <view class="skeleton-characters">
            <view v-for="index in 4" :key="index" class="skeleton-character"></view>
          </view>
        </view>

        <template v-else-if="hasHomeContent">
          <view v-if="featuredStory" class="featured-section">
            <view class="section-kicker-row">
              <text class="section-kicker">继续故事</text>
              <text class="featured-time">
                {{ formatDate(featuredStory.lastMessageTime) }}
              </text>
            </view>

            <view
              class="featured-card"
              @tap="goToStory(featuredStory)"
              @longpress="onStoryLongPress(featuredStory)"
              @contextmenu.prevent="onStoryLongPress(featuredStory)"
            >
              <AvatarImage
                v-if="featuredBackgroundAvatar"
                class="featured-art"
                :src="getAvatarUrl(featuredBackgroundAvatar)"
                :lazy-load="false"
              />
              <view class="featured-image-wash"></view>
              <view class="featured-cover-label">{{ featuredStory.kind === 'group' ? '群聊 · 待续' : '未完 · 待续' }}</view>

              <view class="featured-copy">
                <view class="featured-character-row">
                  <view v-if="featuredStory.kind === 'group'" class="featured-group-avatars">
                    <view
                      v-for="(avatar, idx) in featuredStory.avatars.slice(0, 3)"
                      :key="idx"
                      class="featured-group-avatar-item"
                    >
                      <AvatarImage
                        v-if="avatar.avatarPath"
                        class="featured-group-avatar-img"
                        :src="getAvatarUrl(avatar.avatarPath)"
                        :lazy-load="false"
                      />
                      <text v-else class="featured-group-avatar-initial">{{ avatar.name.slice(0, 1) }}</text>
                    </view>
                  </view>
                  <view v-else class="featured-status-dot"></view>
                  <text class="featured-character">{{ featuredStory.subtitle }}</text>
                </view>
                <text class="featured-title">{{ featuredStory.title }}</text>
                <text class="featured-preview"><text v-if="featuredStory.draft" class="draft-badge">[草稿]</text>{{ featuredStory.draft || featuredStory.preview }}</text>

                <view class="continue-button" @tap.stop="goToStory(featuredStory)">
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

          <view v-if="recentStories.length > 0" class="recent-section">
            <view class="section-heading recent-heading">
              <view class="section-heading-copy">
                <text class="section-title">最近故事</text>
                <text class="section-caption">翻开其他未完的篇章</text>
              </view>
            </view>

            <view class="recent-story-list">
              <view
                v-for="story in recentStories"
                :key="story.key"
                class="story-row"
                @tap="goToStory(story)"
                @longpress="onStoryLongPress(story)"
                @contextmenu.prevent="onStoryLongPress(story)"
              >
                <AvatarImage
                  v-if="story.kind === 'single'"
                  class="story-avatar"
                  :src="getAvatarUrl(story.avatars[0]?.avatarPath || '')"
                />
                <view
                  v-else
                  class="story-group-avatar"
                  :class="`count-${Math.min(story.avatars.length, 3)}`"
                >
                  <view
                    v-for="(avatar, idx) in story.avatars.slice(0, 3)"
                    :key="idx"
                    class="group-avatar-tile"
                    :class="{ 'is-lead': story.avatars.length === 3 && idx === 0 }"
                  >
                    <AvatarImage
                      v-if="avatar.avatarPath"
                      class="group-avatar-img"
                      :src="getAvatarUrl(avatar.avatarPath)"
                    />
                    <text v-else class="group-avatar-fallback">{{ avatar.name.slice(0, 1) }}</text>
                  </view>
                </view>

                <view class="story-copy">
                  <view class="story-meta-row">
                    <view class="story-meta-lead">
                      <text v-if="story.kind === 'group'" class="story-group-badge">群聊</text>
                      <text class="story-character">{{ story.subtitle }}</text>
                    </view>
                    <text class="story-time">
                      {{ formatDate(story.lastMessageTime) }}
                    </text>
                  </view>
                  <text class="story-title">{{ story.title }}</text>
                  <text class="story-preview"><text v-if="story.draft" class="draft-badge">[草稿]</text>{{ story.draft || story.preview }}</text>
                </view>

                <text class="story-chevron">›</text>
              </view>
            </view>
          </view>

          <view v-else-if="featuredStory" class="recent-prompt">
            <text class="recent-prompt-title">这里只有一条故事线</text>
            <text class="recent-prompt-copy">从角色画册选择另一位角色，或从右上角发起群聊，开启不同的相遇。</text>
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
import { deleteGroupSession, getGroupSessions } from "@/api/groupSessions";
import { getBaseUrl } from "@/api/config";
import type { RecentSessionSummary } from "@/api/sessions";
import type { GroupSessionDetail } from "@/types/groupSessions";
import { mergeHomeStories, type HomeSingleSession, type HomeStoryItem } from "@/utils/homeStories";
import { readAllChatDrafts, clearChatDraft } from "@/utils/chatDrafts";
import TabBar from "@/components/common/TabBar.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";
import AppEmptyState from "@/components/common/AppEmptyState.vue";
import AppPageHeader from "@/components/common/AppPageHeader.vue";
import AppPrimaryButton from "@/components/common/AppPrimaryButton.vue";
import AppSoftGlow from "@/components/common/AppSoftGlow.vue";
import { getAvatarUrl } from "@/api/characters";

const personaStore = usePersonaStore();
const isMenuOpen = ref(false);

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");

const singleSessions = ref<HomeSingleSession[]>([]);
const groupSessions = ref<GroupSessionDetail[]>([]);
const storyDrafts = ref<Record<string, string>>({});
const refreshStoryDrafts = () => {
  storyDrafts.value = readAllChatDrafts();
};
const isLoading = ref(false);
let storyLoadVersion = 0;
const RECENT_SESSION_LIMIT = 50;
const QUICK_CHARACTER_LIMIT = 10;

const stories = computed(() => mergeHomeStories(singleSessions.value, groupSessions.value, storyDrafts.value));
const featuredStory = computed(() => stories.value[0] || null);
const featuredBackgroundAvatar = computed(
  () => featuredStory.value?.avatars.find(item => !!item.avatarPath)?.avatarPath || ""
);
const recentStories = computed(() => stories.value.slice(1));
const quickCharacters = computed(() =>
  personaStore.characterList.slice(0, QUICK_CHARACTER_LIMIT)
);
const isHomeLoading = computed(
  () => isLoading.value || personaStore.isLoadingCharacters
);
const hasHomeContent = computed(
  () => stories.value.length > 0 || personaStore.characterList.length > 0
);

let isAndroid = false;
// #ifdef APP-PLUS
isAndroid = uni.getSystemInfoSync().platform === 'android';
// #endif

const fetchSingleSessions = async (): Promise<HomeSingleSession[]> => {
  try {
    const response = await getRecentSessions(RECENT_SESSION_LIMIT);
    return response.sessions.map(decorateRecentSession);
  } catch (error) {
    // 仅在旧后端尚未提供聚合接口时回退，网络故障时避免制造更多请求。
    if (!isUnsupportedRecentSessionsEndpoint(error)) {
      throw error;
    }
    console.warn("Recent sessions endpoint is unavailable; using legacy requests.");
  }

  // 旧后端回退：复用首页已加载的角色列表，逐一读取其会话。
  const allSessions: HomeSingleSession[] = [];
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
  return allSessions;
};

const fetchGroupSessions = async (): Promise<GroupSessionDetail[]> => {
  try {
    const response = await getGroupSessions(RECENT_SESSION_LIMIT, 0);
    return response.sessions ?? [];
  } catch (error) {
    console.warn("Failed to load group sessions", error);
    return [];
  }
};

const loadRecentStories = async () => {
  const version = ++storyLoadVersion;
  const server = getBaseUrl();
  isLoading.value = true;
  try {
    const [singleResult, groupResult] = await Promise.allSettled([
      fetchSingleSessions(),
      fetchGroupSessions(),
    ]);
    if (version !== storyLoadVersion || getBaseUrl() !== server) return;
    if (singleResult.status === "fulfilled") {
      singleSessions.value = singleResult.value;
    } else {
      console.error("Failed to load recent sessions", singleResult.reason);
    }
    if (groupResult.status === "fulfilled") {
      groupSessions.value = groupResult.value;
    }
  } finally {
    if (version === storyLoadVersion) {
      isLoading.value = false;
    }
  }
};

const loadHomeData = async () => {
  await personaStore.loadCharacters(QUICK_CHARACTER_LIMIT, 0);
  await loadRecentStories();
};

const decorateRecentSession = (session: RecentSessionSummary): HomeSingleSession => {
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
  refreshStoryDrafts();
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
  } else if (action === 'create_group') {
    uni.navigateTo({
      url: '/pages/group/create'
    });
  } else if (action === 'add_character') {
    uni.navigateTo({
      url: '/pages/character/create'
    });
  }
};

const goToStory = (story: HomeStoryItem) => {
  if (story.kind === "group") {
    uni.navigateTo({
      url: `/pages/group/detail?sessionId=${story.id}`
    });
    return;
  }
  uni.navigateTo({
    url: `/pages/chat/chat?sessionId=${story.id}`
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

const onStoryLongPress = (story: HomeStoryItem) => {
  uni.vibrateShort({ success: () => {} });
  if (story.kind === "group") {
    uni.showActionSheet({
      itemList: ['删除群聊'],
      success: (res) => {
        if (res.tapIndex !== 0) return;
        uni.showModal({
          title: '删除群聊',
          content: '确定要删除此群聊吗？所有群聊记录与群内记忆数据将无法找回。',
          confirmColor: '#D9655D',
          cancelColor: '#7C8983',
          success: async (mRes) => {
            if (!mRes.confirm) return;
            try {
              await deleteGroupSession(story.id);
              clearChatDraft("group", story.id);
              refreshStoryDrafts();
              await loadRecentStories();
              uni.showToast({ title: '删除成功', icon: 'success' });
            } catch (e: unknown) {
              console.error("Failed to delete group session", e);
              const errMessage = e instanceof Error ? e.message : "删除失败，请检查网络与后端配置";
              uni.showToast({ title: errMessage || '删除失败，请检查网络与后端配置', icon: 'none', duration: 3000 });
            }
          }
        });
      }
    });
    return;
  }

  const session = story.singleSession;
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
                clearChatDraft("single", session.id);
                refreshStoryDrafts();
                useChatSettingsStore().removeSession(session.id);
                await loadRecentStories();
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
      await loadRecentStories();
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
