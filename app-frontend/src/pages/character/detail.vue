<template>
  <view class="detail-container app-motion-enter" v-if="character">
    <!-- 头部导航栏 -->
    <view class="header">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="title">人物档案</text>
      <view class="header-right">
        <view class="header-btn sync-btn" @tap="quickUpdateFromCard">
          <image class="sync-icon" src="/static/icons/drawer_sync.svg" mode="aspectFit" />
        </view>
        <view class="header-btn edit-btn" @tap="goToEdit">
          <image class="edit-icon" src="/static/icons/char_pencil.svg" mode="aspectFit" />
        </view>
      </view>
    </view>

    <scroll-view scroll-y class="scroll-content">
      <view class="scroll-inner">
        <!-- 角色立绘面板 -->
        <view class="portrait-panel">
          <!-- 模糊氛围背景 -->
          <AvatarImage
            class="portrait-blur-bg" 
            :src="getAvatarUrl(character.avatar_path || '')"
            :lazy-load="false"
          />
          <!-- 前景高清立绘卡 -->
          <view class="portrait-card-wrapper">
            <AvatarImage
              class="portrait-img" 
              :src="getAvatarUrl(character.avatar_path || '')"
              :lazy-load="false"
              @tap="previewPortrait"
            />
          </view>
          <view class="portrait-overlay" @tap="previewPortrait"></view>
          
          <view class="change-portrait-btn" @tap="changePortrait">
            <image class="change-portrait-icon" src="/static/icons/char_camera.svg" mode="aspectFit" />
            <text class="change-portrait-text">更换立绘</text>
          </view>
        </view>

        <!-- 角色基本名称与标签区域 -->
        <view class="char-header-section">
          <text class="archive-eyebrow">CHARACTER FILE</text>
          <text class="char-name">{{ character.name }}</text>
          <text class="char-summary">
            {{ character.description?.trim() || "这位角色还没有留下档案摘要。" }}
          </text>
          <view class="tag-row" v-if="character.personality || (character.tags && character.tags.length > 0)">
            <view 
              class="personality-tag" 
              v-for="tag in personalityTags" 
              :key="'pers-' + tag"
            >
              {{ tag }}
            </view>
            <view 
              class="character-tag" 
              v-for="tag in (character.tags || [])" 
              :key="'tag-' + tag"
            >
              #{{ tag }}
            </view>
          </view>
          <view class="archive-stats">
            <view class="archive-stat">
              <text class="archive-stat-value">{{ sessions.length }}</text>
              <text class="archive-stat-label">故事线</text>
            </view>
            <view class="archive-stat-divider"></view>
            <view class="archive-stat">
              <text class="archive-stat-value">{{ lorebookEntriesCount }}</text>
              <text class="archive-stat-label">世界条目</text>
            </view>
          </view>
        </view>

        <!-- 页签导航栏 -->
        <view class="tabs-nav">
          <view
            class="tab-item"
            :class="{ 'is-active': activeTab === 'profile' }"
            @tap="activeTab = 'profile'"
          >
            <text class="tab-label">档案</text>
          </view>
          <view 
            class="tab-item" 
            :class="{ 'is-active': activeTab === 'lorebook' }"
            @tap="activeTab = 'lorebook'"
          >
            <text class="tab-label">世界</text>
          </view>
          <view
            class="tab-item"
            :class="{ 'is-active': activeTab === 'memory' }"
            @tap="openMemoryArchive"
          >
            <text class="tab-label">记忆</text>
          </view>
          <view
            class="tab-item"
            :class="{ 'is-active': activeTab === 'sessions' }"
            @tap="activeTab = 'sessions'"
          >
            <text class="tab-label">故事线</text>
          </view>
        </view>

        <!-- Tab 1: 故事宇宙分支列表 -->
        <view v-if="activeTab === 'sessions'" class="branches-tab-content">
          <!-- 视图模式切换栏（平铺列表 vs 时空分支树） -->
          <view v-if="sessions.length > 0" class="view-mode-toggle-row">
            <view 
              class="toggle-pill" 
              :class="{ 'is-active': viewMode === 'tree' }" 
              @tap="viewMode = 'tree'"
            >
              <image class="toggle-pill-icon" src="/static/icons/char_branch.svg" mode="aspectFit" />
              <text class="toggle-pill-text">时空分叉树</text>
            </view>
            <view 
              class="toggle-pill" 
              :class="{ 'is-active': viewMode === 'list' }" 
              @tap="viewMode = 'list'"
            >
              <image class="toggle-pill-icon" src="/static/icons/char_list.svg" mode="aspectFit" />
              <text class="toggle-pill-text">时间线列表</text>
            </view>
          </view>

          <!-- 1) 树形图视图 -->
          <view v-if="viewMode === 'tree' && sessions.length > 0" class="tree-view-wrapper">
            <BranchTreeView 
              :sessions="sessions" 
              @tap-node="resumeSession"
              @longpress-node="onSessionLongPress"
              @branch-node="handleTreeNodeBranch"
            />
          </view>

          <!-- 2) 传统扁平列表视图 -->
          <view v-else-if="viewMode === 'list' && sessions.length > 0" class="branches-list">
            <view 
              class="branch-card" 
              :class="getAffectionClass(session.persona?.affection_score)"
              v-for="session in sessions" 
              :key="session.id"
              @tap="resumeSession(session)"
              @longpress="onSessionLongPress(session)"
              @contextmenu.prevent="onSessionLongPress(session)"
            >
              <view class="branch-card-header">
                <view class="branch-title-area">
                  <text class="branch-name">{{ session.title || '平行宇宙会话' }}</text>
                  <text class="branch-parent-tag" v-if="session.parent_session_id">
                     衍生自: {{ getParentSessionTitle(session.parent_session_id) }}
                  </text>
                </view>
                <view class="branch-meta">
                  <view class="meta-item mood">
                    <text class="meta-label">心境:</text>
                    <text class="meta-value">{{ session.persona?.current_mood || '平静' }}</text>
                  </view>
                  <view class="meta-item affection">
                    <text class="meta-label">好感:</text>
                    <view class="affection-score-row">
                      <text class="meta-value score">{{ session.persona?.affection_score || 0 }}</text>
                      <image class="affection-heart-icon" src="/static/icons/meta_heart.svg" mode="aspectFit" />
                    </view>
                  </view>
                </view>
              </view>
              <text class="branch-preview">{{ session.lastMessage || '尚无对话记录...' }}</text>
              <text class="branch-date">{{ formatDate(session.updated_at) }}</text>
            </view>
          </view>

          <!-- 平行宇宙分支空状态 -->
          <view v-if="sessions.length === 0" class="empty-branches">
            <text class="empty-branches-text">尚未开启任何故事宇宙。点击下方开启平行世界。</text>
          </view>
        </view>

        <!-- Tab 2: 人设细节卡片 -->
        <CharacterProfileTab 
          v-if="activeTab === 'profile'" 
          :character="character" 
        />

        <!-- Tab 3: 专属与绑定世界书列表 -->
        <view v-show="activeTab === 'lorebook'">
          <CharacterLorebookTab 
            :character="character" 
            :characterId="characterId" 
            @refresh="loadCharacterData"
            @entries-count="onEntriesCountUpdate"
          />
        </view>

        <!-- 角色记忆导航：先选择故事线，再查看对应记忆。 -->
        <view v-if="activeTab === 'memory'" class="memory-archive">
          <view class="memory-archive-header">
            <view class="memory-archive-heading">
              <text class="memory-archive-kicker">MEMORY ARCHIVE</text>
              <text class="memory-archive-title">故事记忆档案</text>
              <text class="memory-archive-description">
                每条故事线都保存着独立的经历与关系。选择一段故事，查看它记住了什么。
              </text>
            </view>
            <view v-if="memoryStoryCount > 0" class="memory-archive-count">
              <text class="memory-archive-count-number">{{ memoryStoryCount }}</text>
              <text class="memory-archive-count-label">条故事线</text>
            </view>
          </view>

          <view v-if="isMemoryOverviewLoading && !memoryOverviewLoaded" class="memory-navigation-loading">
            <view class="memory-nav-skeleton featured"></view>
            <view class="memory-nav-skeleton"></view>
            <view class="memory-nav-skeleton short"></view>
          </view>

          <view v-else-if="memoryOverviewFailed" class="memory-archive-empty compact">
            <text class="memory-empty-title">记忆档案加载失败</text>
            <text class="memory-empty-description">请检查后端连接后重试。</text>
            <view class="memory-empty-action" @tap="loadMemoryOverview()">
              <text>重新加载</text>
            </view>
          </view>

          <template v-else-if="recentMemorySession">
            <view class="memory-section-heading">
              <text class="memory-section-title">最近活跃</text>
              <text class="memory-section-caption">从上次停下的地方继续</text>
            </view>

            <view class="memory-featured-card">
              <view class="memory-featured-glow"></view>
              <view class="memory-featured-topline">
                <view class="memory-status-pill">
                  <view class="memory-status-dot"></view>
                  <text>最近故事</text>
                </view>
                <text class="memory-story-date">
                  {{ formatDate(recentMemorySession.lastMessageTime || recentMemorySession.updated_at) }}
                </text>
              </view>
              <text class="memory-featured-title">
                {{ recentMemorySession.title || "未命名故事" }}
              </text>
              <text class="memory-featured-preview">
                {{ recentMemorySession.lastMessage || "这段故事还没有留下对话记录。" }}
              </text>
              <text v-if="recentMemorySession.parent_session_id" class="memory-featured-origin">
                延续自「{{ getParentSessionTitle(recentMemorySession.parent_session_id) }}」
              </text>
              <view class="memory-featured-stats">
                <text>{{ recentMemorySession.memoryStats.effective_total }} 条有效记忆</text>
                <text>·</text>
                <text>{{ recentMemorySession.memoryStats.inherited_active }} 条继承</text>
              </view>
              <view class="memory-card-actions">
                <view class="memory-card-action primary" @tap="openMemoryModal(recentMemorySession)">
                  <image src="/static/icons/drawer_brain.svg" mode="aspectFit" />
                  <text>查看记忆</text>
                </view>
                <view class="memory-card-action ghost" @tap="resumeSession(recentMemorySession)">
                  <text>进入故事</text>
                  <text class="memory-card-action-arrow">→</text>
                </view>
              </view>
            </view>

            <view v-if="otherMemorySessions.length > 0" class="memory-story-section">
              <view class="memory-section-heading">
                <text class="memory-section-title">其他故事线</text>
                <text class="memory-section-caption">记忆沿着每一次选择生长</text>
              </view>

              <view class="memory-story-list">
                <view
                  v-for="session in otherMemorySessions"
                  :key="session.id"
                  class="memory-story-row"
                >
                  <view class="memory-story-rail">
                    <view class="memory-story-node"></view>
                    <view class="memory-story-line"></view>
                  </view>
                  <view class="memory-story-card" @tap="openMemoryModal(session)">
                    <view class="memory-story-card-header">
                      <view class="memory-story-copy">
                        <text class="memory-story-title">{{ session.title || "未命名故事" }}</text>
                        <text class="memory-story-origin">
                          {{ session.parent_session_id ? `延续自「${getParentSessionTitle(session.parent_session_id)}」` : "独立故事线" }}
                        </text>
                      </view>
                      <view class="memory-story-open">
                        <image src="/static/icons/drawer_brain.svg" mode="aspectFit" />
                        <text>查看记忆</text>
                      </view>
                    </view>
                    <text class="memory-story-stats">
                      {{ session.memoryStats.effective_total }} 条有效记忆
                      · {{ session.memoryStats.inherited_active }} 条继承
                    </text>
                    <text class="memory-story-preview">
                      {{ session.lastMessage || "这段故事还没有留下对话记录。" }}
                    </text>
                    <view class="memory-story-footer">
                      <text class="memory-story-date">
                        {{ formatDate(session.lastMessageTime || session.updated_at) }}
                      </text>
                      <view class="memory-story-enter" @tap.stop="resumeSession(session)">
                        <text>进入故事</text>
                        <text>→</text>
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </template>

          <view v-else class="memory-archive-empty">
            <view class="memory-orbit">
              <view class="memory-orbit-ring"></view>
              <view class="memory-orbit-core"></view>
            </view>
            <text class="memory-empty-title">记忆还在等待第一段故事</text>
            <text class="memory-empty-description">
              开始对话后，值得记住的经历与关系会在这里形成档案。
            </text>
            <view class="memory-empty-action" @tap="openNewBranchModal">
              <text>开启第一段故事</text>
              <text>→</text>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>

    <!-- 底部操作按钮 -->
    <view class="footer">
      <view class="action-btn" @tap="openNewBranchModal">
        <image class="action-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
        <text class="action-btn-text">开启新的故事线</text>
      </view>
    </view>

    <!-- 向量记忆管理弹窗 -->
    <MemoryManagerModal
      v-if="isMemoryModalOpen"
      :isOpen="isMemoryModalOpen"
      :sessionId="activeMemorySessionId"
      :contextTitle="selectedMemorySession?.title || ''"
      localLabel="此故事"
      @close="closeMemoryModal"
    />

    <!-- 新建平行宇宙分支模态框 -->
    <NewSessionModal 
      v-model:isOpen="isNewBranchModalOpen" 
      :alternateGreetings="(character?.extensions?.alternate_greetings as string[] | undefined)"
      :characterName="character?.name"
      @confirm="startNewBranch"
    />

    <!-- 重命名会话分支模态框 -->
    <RenameSessionModal
      :isOpen="renamingSessionId !== null"
      :title="newSessionTitle"
      @close="cancelRename"
      @save="saveRename"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { getCharacter, updateCharacter, uploadAvatar, getAvatarUrl, parseCharacter } from "@/api/characters";
import type { CharacterDetail } from "@/api/characters";
import {
  getAllSessions,
  deleteSession,
  updateSessionTitle,
  createSession,
  getCharacterMemoryOverview
} from "@/api/sessions";
import type { MemoryStats, SessionSummary } from "@/api/sessions";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import BranchTreeView from "@/components/chat/BranchTreeView.vue";
import { usePersonaStore } from "@/store/personaStore";
import CharacterProfileTab from "@/components/character/CharacterProfileTab.vue";
import CharacterLorebookTab from "@/components/character/CharacterLorebookTab.vue";
import MemoryManagerModal from "@/components/chat/MemoryManagerModal.vue";

// 引入重命名分支子组件
import RenameSessionModal from "@/components/common/RenameSessionModal.vue";
import AvatarImage from "@/components/common/AvatarImage.vue";

const personaStore = usePersonaStore();

interface CharacterSessionItem extends SessionSummary {
  lastMessage: string;
  lastMessageTime: string;
}

interface MemoryStoryItem {
  id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  lastMessage: string;
  lastMessageTime: string;
  memoryStats: MemoryStats;
}

const characterId = ref<number | null>(null);
const character = ref<CharacterDetail | null>(null);
const sessions = ref<CharacterSessionItem[]>([]);
const isNewBranchModalOpen = ref(false);
const isMemoryModalOpen = ref(false);
const selectedMemorySession = ref<MemoryStoryItem | null>(null);
const memoryStories = ref<MemoryStoryItem[]>([]);
const memoryStoryCount = ref(0);
const recentMemorySessionId = ref<number | null>(null);
const isMemoryOverviewLoading = ref(false);
const memoryOverviewLoaded = ref(false);
const memoryOverviewFailed = ref(false);

const recentMemorySession = computed(() => {
  if (recentMemorySessionId.value === null) return memoryStories.value[0] || null;
  return (
    memoryStories.value.find((session) => session.id === recentMemorySessionId.value) ||
    memoryStories.value[0] ||
    null
  );
});
const otherMemorySessions = computed(() =>
  memoryStories.value.filter((session) => session.id !== recentMemorySession.value?.id)
);
const activeMemorySessionId = computed(() => selectedMemorySession.value?.id || null);

const openMemoryModal = (session: MemoryStoryItem) => {
  selectedMemorySession.value = session;
  isMemoryModalOpen.value = true;
};

const closeMemoryModal = () => {
  isMemoryModalOpen.value = false;
  selectedMemorySession.value = null;
};

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");
const activeParentSessionId = ref<number | null>(null);
const activeTab = ref<"profile" | "lorebook" | "memory" | "sessions">("profile");
const viewMode = ref<"list" | "tree">("tree");

const openMemoryArchive = async () => {
  activeTab.value = "memory";
  if (!memoryOverviewLoaded.value) {
    await loadMemoryOverview();
  }
};

const lorebookEntriesCount = ref(0);

const onEntriesCountUpdate = (count: number) => {
  lorebookEntriesCount.value = count;
};

const getParentSessionTitle = (parentId: number | null) => {
  if (!parentId) return "";
  const parent = sessions.value.find(s => s.id === parentId);
  return parent ? parent.title : `会话 #${parentId}`;
};

const personalityTags = computed(() => {
  if (!character.value?.personality) return [];
  return character.value.personality.split(/[,，\s]+/).filter(tag => tag.trim() !== "");
});

const getAffectionClass = (score: number | undefined | null) => {
  if (score === undefined || score === null) return "";
  if (score >= 80) return "affection-high";
  if (score <= 30) return "affection-low";
  return "";
};

onLoad((options) => {
  if (options && options.id) {
    characterId.value = parseInt(options.id, 10);
  }
});

onShow(() => {
  if (characterId.value !== null) {
    loadCharacterData(characterId.value);
  }
});

async function loadCharacterData(id: number) {
  try {
    const [char, sessionPage] = await Promise.all([
      getCharacter(id),
      getAllSessions(id, true)
    ]);
    character.value = char;
    sessions.value = sessionPage.sessions.map((session) => ({
      ...session,
      lastMessage: session.last_message?.content
        ? session.last_message.content.replace(/\s+/g, " ").trim()
        : "",
      lastMessageTime: session.last_message?.created_at || session.updated_at
    }));

    if (activeTab.value === "memory") {
      await loadMemoryOverview();
    } else {
      memoryOverviewLoaded.value = false;
      memoryOverviewFailed.value = false;
      memoryStories.value = [];
      memoryStoryCount.value = sessionPage.total;
      recentMemorySessionId.value = null;
    }
  } catch (e) {
    console.error("Failed to load character detail", e);
  }
};

async function loadMemoryOverview() {
  if (characterId.value === null || isMemoryOverviewLoading.value) return;
  isMemoryOverviewLoading.value = true;
  memoryOverviewFailed.value = false;
  try {
    const pageSize = 100;
    let page = await getCharacterMemoryOverview(characterId.value, pageSize, 0);
    const overviewSessions = [...page.sessions];
    let nextOffset = page.offset + page.sessions.length;

    while (page.has_more) {
      page = await getCharacterMemoryOverview(characterId.value, pageSize, nextOffset);
      overviewSessions.push(...page.sessions);
      nextOffset = page.offset + page.sessions.length;
    }

    memoryStories.value = overviewSessions.map((session) => ({
      id: session.session_id,
      title: session.title,
      parent_session_id: session.parent_session_id,
      created_at: session.created_at,
      updated_at: session.updated_at,
      lastMessage: session.last_message?.content
        ? session.last_message.content.replace(/\s+/g, " ").trim()
        : "",
      lastMessageTime: session.last_message?.created_at || session.updated_at,
      memoryStats: session.memory_stats
    }));
    memoryStoryCount.value = page.story_count;
    recentMemorySessionId.value = page.recent_session_id;
    memoryOverviewLoaded.value = true;
  } catch (e) {
    console.error("Failed to load character memory overview", e);
    memoryOverviewFailed.value = true;
    uni.showToast({ title: "加载记忆档案失败", icon: "none" });
  } finally {
    isMemoryOverviewLoading.value = false;
  }
}

const goBack = () => {
  const pages = getCurrentPages();
  if (pages.length > 1) {
    uni.navigateBack();
  } else {
    uni.switchTab({
      url: "/pages/character/index"
    });
  }
};

const goToEdit = () => {
  if (characterId.value !== null) {
    uni.navigateTo({
      url: `/pages/character/create?id=${characterId.value}`
    });
  }
};

const runQuickUpdate = async (tempFilePath: string, isPng: boolean) => {
  if (characterId.value === null || !character.value) return;
  uni.showLoading({ title: '正在解析角色卡...' });
  try {
    const parseRes = await parseCharacter(tempFilePath);
    
    let avatarPath = character.value.avatar_path || "";
    // 如果是 PNG 格式角色卡，自动上传并更新头像
    if (isPng) {
      uni.showLoading({ title: '正在上传头像...' });
      try {
        const uploadRes = await uploadAvatar(tempFilePath);
        avatarPath = uploadRes.avatar_path;
      } catch (uploadErr) {
        console.error("Auto avatar upload failed", uploadErr);
      }
    } else if (parseRes.data.avatar_path) {
      avatarPath = parseRes.data.avatar_path;
    }

    const updatedData = {
      ...character.value,
      ...parseRes.data,
      avatar_path: avatarPath
    };

    uni.showLoading({ title: '正在更新角色信息...' });
    await updateCharacter(characterId.value, updatedData);
    await personaStore.loadCharacters();
    await loadCharacterData(characterId.value);
    
    uni.showToast({ title: '更新角色信息成功', icon: 'success' });
  } catch (e) {
    console.error("Quick update failed", e);
    uni.showToast({ title: '更新失败，请检查格式', icon: 'none' });
  } finally {
    uni.hideLoading();
  }
};

const quickUpdateFromCard = () => {
  if (characterId.value === null || !character.value) return;
  
  uni.showModal({
    title: "快捷更新",
    content: "导入新角色卡将直接覆盖该角色的当前设定（不会影响聊天记录和好感度）。是否继续？",
    success: (modalRes) => {
      if (!modalRes.confirm) return;

      // #ifdef APP-PLUS
      uni.chooseImage({
        count: 1,
        sizeType: ['original'],
        sourceType: ['album'],
        success: (res) => {
          runQuickUpdate(res.tempFilePaths[0], true);
        },
        fail: (err) => {
          console.log("选择图片取消或失败", err);
        }
      });
      // #endif

      // #ifndef APP-PLUS
      uni.chooseFile({
        count: 1,
        type: "all",
        extension: [".png", ".json"],
        success: (res) => {
          const path = res.tempFilePaths[0];
          const isPng = path.toLowerCase().endsWith('.png');
          runQuickUpdate(path, isPng);
        },
        fail: (err) => {
          console.log("选择文件取消或失败", err);
        }
      });
      // #endif
    }
  });
};

const previewPortrait = () => {
  const avatar = character.value?.avatar_path;
  if (avatar) {
    const url = getAvatarUrl(avatar);
    uni.previewImage({
      urls: [url],
      current: url
    });
  }
};

const changePortrait = () => {
  uni.chooseImage({
    count: 1,
    sizeType: ['original'],
    sourceType: ['album', 'camera'],
    success: async (res) => {
      const tempPath = res.tempFilePaths[0];
      try {
        uni.showLoading({ title: '正在上传立绘...' });
        const uploadRes = await uploadAvatar(tempPath);
        
        if (character.value && characterId.value !== null) {
          const updatedCharData = {
            ...character.value,
            avatar_path: uploadRes.avatar_path
          };
          await updateCharacter(characterId.value, updatedCharData);
          character.value.avatar_path = uploadRes.avatar_path;
          uni.showToast({ title: '立绘更换成功', icon: 'success' });
        }
      } catch (e) {
        console.error("Change portrait failed", e);
        uni.showToast({ title: '立绘更换失败', icon: 'none' });
      } finally {
        uni.hideLoading();
      }
    }
  });
};

const openNewBranchModal = () => {
  activeParentSessionId.value = null;
  isNewBranchModalOpen.value = true;
}

const handleTreeNodeBranch = (session: any) => {
  activeParentSessionId.value = session.id;
  isNewBranchModalOpen.value = true;
};

const startNewBranch = async (payload: { title: string; greeting_index: number | null }) => {
  if (characterId.value === null) return;
  try {
    uni.showLoading({ title: '正在开启故事...' });
    const res = await createSession({
      character_id: characterId.value,
      parent_session_id: activeParentSessionId.value,
      title: payload.title,
      greeting_index: payload.greeting_index !== null ? payload.greeting_index : undefined
    });
    uni.hideLoading();
    uni.navigateTo({
      url: `/pages/chat/chat?sessionId=${res.session_id}`
    });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '开启新平行故事失败', icon: 'none' });
  }
};

const resumeSession = (session: any) => {
  uni.navigateTo({
    url: `/pages/chat/chat?sessionId=${session.id}`
  });
};

const onSessionLongPress = (session: any) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ['从此分支分叉新世界', '重命名分支', '删除分支'],
    success: (res) => {
      if (res.tapIndex === 0) {
        activeParentSessionId.value = session.id;
        isNewBranchModalOpen.value = true;
      } else if (res.tapIndex === 1) {
        renamingSessionId.value = session.id;
        newSessionTitle.value = session.title;
      } else if (res.tapIndex === 2) {
        const charId = characterId.value;
        uni.showModal({
          title: '删除宇宙分支',
          content: '确定要删除此平行世界故事线吗？该人格的所有记忆将被抹去。',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm && charId !== null) {
              try {
                await deleteSession(session.id);
                await loadCharacterData(charId);
                uni.showToast({ title: '删除成功', icon: 'success' });
              } catch (e: any) {
                console.error("Failed to delete branch", e);
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

const saveRename = async (newTitle: string) => {
  if (renamingSessionId.value !== null && newTitle.trim() !== "") {
    try {
      await updateSessionTitle(renamingSessionId.value, newTitle.trim());
      cancelRename();
      if (characterId.value !== null) {
        await loadCharacterData(characterId.value);
      }
    } catch (e) {
      console.error("Failed to update branch title", e);
    }
  }
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

<style scoped src="./detail.css"></style>
