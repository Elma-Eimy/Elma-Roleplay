<template>
  <view class="detail-container" v-if="character">
    <!-- 头部导航栏 -->
    <view class="header">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="title">角色设定</text>
      <view class="header-btn edit-btn" @tap="goToEdit">
        <image class="edit-icon" src="/static/icons/char_pencil.svg" mode="aspectFit" />
      </view>
    </view>

    <scroll-view scroll-y class="scroll-content">
      <view class="scroll-inner">
        <!-- 角色立绘面板 -->
        <view class="portrait-panel">
          <image 
            class="portrait-img" 
            :src="getAvatarUrl(character.avatar_path || '') || '/static/default-avatar.png'" 
            mode="aspectFill" 
            @tap="previewPortrait"
          />
          <view class="portrait-overlay" @tap="previewPortrait"></view>
          
          <view class="change-portrait-btn" @tap="changePortrait">
            <image class="change-portrait-icon" src="/static/icons/char_camera.svg" mode="aspectFit" />
            <text class="change-portrait-text">更换立绘</text>
          </view>
        </view>

        <!-- 角色基本名称与标签区域 -->
        <view class="char-header-section">
          <text class="char-name">{{ character.name }}</text>
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
        </view>

        <!-- 页签导航栏 -->
        <view class="tabs-nav">
          <view 
            class="tab-item" 
            :class="{ 'is-active': activeTab === 'sessions' }"
            @tap="activeTab = 'sessions'"
          >
            <text class="tab-label">故事宇宙 ({{ sessions.length }})</text>
          </view>
          <view 
            class="tab-item" 
            :class="{ 'is-active': activeTab === 'profile' }"
            @tap="activeTab = 'profile'"
          >
            <text class="tab-label">人设细节</text>
          </view>
          <view 
            class="tab-item" 
            :class="{ 'is-active': activeTab === 'lorebook' }"
            @tap="activeTab = 'lorebook'"
          >
            <text class="tab-label">专属世界书 ({{ lorebookEntriesCount }})</text>
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
      </view>
    </scroll-view>

    <!-- 底部操作按钮 -->
    <view class="footer">
      <view class="action-btn" @tap="openNewBranchModal">
        <image class="action-icon" src="/static/icons/header_plus.svg" mode="aspectFit" />
        <text class="action-btn-text">开启全新平行故事</text>
      </view>
    </view>

    <!-- 新建平行宇宙分支模态框 -->
    <NewSessionModal 
      v-model:isOpen="isNewBranchModalOpen" 
      :alternateGreetings="(character?.extensions?.alternate_greetings as string[] | undefined)"
      :characterName="character?.name"
      @confirm="startNewBranch"
    />

    <!-- 重命名会话分支模态框 -->
    <view v-if="renamingSessionId !== null" class="rename-modal-backdrop">
      <view class="rename-modal">
        <text class="modal-title">重命名分支</text>
        <input class="rename-input" v-model="newSessionTitle" placeholder="请输入新分支名称..." :focus="true" />
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="cancelRename">取消</view>
          <view class="modal-btn save" @tap="saveRename">保存</view>
        </view>
      </view>
    </view>

  </view>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { onLoad, onShow } from "@dcloudio/uni-app";
import { getCharacter, updateCharacter, uploadAvatar, getAvatarUrl } from "@/api/characters";
import type { CharacterDetail } from "@/api/characters";
import { getSessions, deleteSession, updateSessionTitle, createSession, getSessionHistory } from "@/api/sessions";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import BranchTreeView from "@/components/chat/BranchTreeView.vue";
import { usePersonaStore } from "@/store/personaStore";
import CharacterProfileTab from "@/components/character/CharacterProfileTab.vue";
import CharacterLorebookTab from "@/components/character/CharacterLorebookTab.vue";

const personaStore = usePersonaStore();

const characterId = ref<number | null>(null);
const character = ref<CharacterDetail | null>(null);
const sessions = ref<any[]>([]);
const isNewBranchModalOpen = ref(false);

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");
const activeParentSessionId = ref<number | null>(null);
const activeTab = ref<"sessions" | "profile" | "lorebook">("sessions");
const viewMode = ref<"list" | "tree">("tree");

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

const loadCharacterData = async (id: number) => {
  try {
    const char = await getCharacter(id);
    character.value = char;

    const res = await getSessions(id);
    const sortedSessions = res.sessions;
    
    // 获取每个平行宇宙分支会话的最后一条消息预览内容，并对换行符进行空格清洗
    const decoratedSessions = await Promise.all(
      sortedSessions.map(async (s) => {
        try {
          const hRes = await getSessionHistory(s.id, 1);
          if (hRes.messages.length > 0) {
            const lastMsgObj = hRes.messages[hRes.messages.length - 1];
            const lastMsg = lastMsgObj.content || "";
            const cleanMsg = lastMsg ? lastMsg.replace(/\s+/g, ' ').trim() : "";
            return {
              ...s,
              lastMessage: cleanMsg,
              lastMessageTime: lastMsgObj.created_at || s.updated_at
            };
          } else {
            return {
              ...s,
              lastMessage: "",
              lastMessageTime: s.updated_at
            };
          }
        } catch (e) {
          return { ...s, lastMessage: "", lastMessageTime: s.updated_at };
        }
      })
    );

    // 按最近消息发送时间降序对分支会话进行排序
    decoratedSessions.sort(
      (a, b) => new Date(b.lastMessageTime).getTime() - new Date(a.lastMessageTime).getTime()
    );

    sessions.value = decoratedSessions;
  } catch (e) {
    console.error("Failed to load character detail", e);
  }
};

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
    sizeType: ['compressed'],
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
};

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

const saveRename = async () => {
  if (renamingSessionId.value !== null && newSessionTitle.value.trim() !== "") {
    try {
      await updateSessionTitle(renamingSessionId.value, newSessionTitle.value.trim());
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

<style scoped>
.detail-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100%;
  background-color: #fafafa;
}

/* ===== 头部样式 ===== */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  padding-left: 36rpx;
  padding-right: 36rpx;
  background-color: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.back-btn, .header-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.back-btn:active, .header-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
}

/* ===== 内容滚动区域 ===== */
.scroll-content {
  flex: 1;
  height: 0;
  min-height: 0;
}

.scroll-inner {
  padding-bottom: 220rpx;
}

/* ===== 角色立绘面板 ===== */
.portrait-panel {
  position: relative;
  width: 100%;
  height: 680rpx;
  background-color: #f2f2f7;
  overflow: hidden;
}

.portrait-img {
  width: 100%;
  height: 100%;
}

.portrait-img :deep(img) {
  object-fit: cover !important;
  object-position: center top !important;
}

.portrait-img :deep(div) {
  background-size: cover !important;
  background-position: center top !important;
}

.portrait-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 180rpx;
  background: linear-gradient(to top, rgba(250, 250, 250, 1), rgba(250, 250, 250, 0));
}

.change-portrait-btn {
  position: absolute;
  bottom: 30rpx;
  right: 36rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 14rpx 28rpx;
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  border-radius: 30rpx;
  border: 1px solid rgba(0, 0, 0, 0.05);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
  transition: all 0.2s;
}

.change-portrait-btn:active {
  transform: scale(0.95);
  background-color: #ffffff;
}

.change-portrait-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #1c1c1e;
}

/* ===== 角色头部基本设定 ===== */
.char-header-section {
  padding: 0 36rpx 28rpx 36rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.char-name {
  font-size: 44rpx;
  font-weight: 700;
  color: #1c1c1e;
  letter-spacing: -0.5px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.personality-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #8e8e93;
  background-color: rgba(0, 0, 0, 0.03);
  padding: 6rpx 20rpx;
  border-radius: 40rpx;
  border: 1px solid rgba(0, 0, 0, 0.03);
}



/* ===== 宇宙会话分支列表 ===== */
.branches-header {
  padding: 24rpx 36rpx 16rpx 48rpx;
}

.branches-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.branches-list {
  padding: 0 36rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.branch-card {
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 28rpx 28rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.branch-card:active {
  transform: scale(0.98);
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

.branch-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12rpx;
}

.branch-name {
  font-size: 32rpx;
  font-weight: 600;
  color: #1c1c1e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.branch-title-area {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  flex: 1;
  min-width: 0;
}

.branch-parent-tag {
  font-size: 24rpx;
  color: #8e8e93;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: inline-flex;
  align-items: center;
}

.branch-meta {
  display: flex;
  gap: 12rpx;
  flex-shrink: 0;
}

.meta-item {
  display: flex;
  gap: 4rpx;
  font-size: 24rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  padding: 6rpx 16rpx;
  border-radius: 40rpx;
}

.meta-label {
  color: #8e8e93;
}

.meta-value {
  color: #1c1c1e;
  font-weight: 600;
}

.meta-value.score {
  color: #1c1c1e;
}

.branch-preview {
  font-size: 28rpx;
  color: #8e8e93;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.branch-date {
  font-size: 24rpx;
  color: #c7c7cc;
  text-align: right;
  font-weight: 500;
}

.empty-branches {
  padding: 64rpx 0;
  display: flex;
  justify-content: center;
  text-align: center;
}

.empty-branches-text {
  font-size: 26rpx;
  color: #8e8e93;
  line-height: 1.5;
}

/* ===== 底部操作栏 ===== */
.footer {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  padding: 24rpx 36rpx calc(env(safe-area-inset-bottom, 24rpx) + 24rpx);
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 60;
}

.action-btn {
  height: 88rpx;
  background-color: #1c1c1e;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  transition: all 0.25s ease;
}

.action-btn:active {
  background-color: #000000;
  transform: scale(0.975);
}

.action-btn-text {
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
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

/* Custom SVG Icon Styles */
.back-icon {
  width: 44rpx;
  height: 44rpx;
}
.edit-icon {
  width: 36rpx;
  height: 36rpx;
}
.change-portrait-icon {
  width: 32rpx;
  height: 32rpx;
}
.action-icon {
  width: 40rpx;
  height: 40rpx;
}

/* Fallback Unicode Icon Styles */
.back-icon-fallback {
  display: none;
}
.edit-icon-fallback {
  display: none;
}
.change-portrait-icon-fallback {
  display: none;
}
.action-icon-fallback {
  display: none;
}

/* ===== 页签导航 (Tabs Nav) ===== */
.tabs-nav {
  display: flex;
  margin: 0 36rpx 28rpx 36rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  border-radius: 20rpx;
  padding: 6rpx;
}

.tab-item {
  flex: 1;
  padding: 16rpx 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16rpx;
  transition: all 0.2s ease;
}

.tab-item.is-active {
  background-color: #ffffff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.tab-label {
  font-size: 24rpx;
  font-weight: 600;
  color: #8e8e93;
  transition: color 0.2s ease;
}

.tab-item.is-active .tab-label {
  color: #1c1c1e;
}



/* ===== 视图模式切换栏 ===== */
.view-mode-toggle-row {
  display: flex;
  margin: 0 36rpx 28rpx 36rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  border-radius: 16rpx;
  padding: 4rpx;
}

.toggle-pill {
  flex: 1;
  padding: 12rpx 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12rpx;
  transition: all 0.2s ease;
}

.toggle-pill.is-active {
  background-color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.toggle-pill-text {
  font-size: 22rpx;
  font-weight: 600;
  color: #8e8e93;
  transition: color 0.2s ease;
}

.toggle-pill.is-active .toggle-pill-text {
  color: #1c1c1e;
}

.toggle-pill-icon {
  width: 28rpx;
  height: 28rpx;
  margin-right: 8rpx;
  filter: opacity(0.4) grayscale(1);
  transition: all 0.2s ease;
}

.toggle-pill.is-active .toggle-pill-icon {
  filter: opacity(0.95) grayscale(0);
}

.affection-score-row {
  display: flex;
  align-items: center;
  gap: 4rpx;
}

.affection-heart-icon {
  width: 24rpx;
  height: 24rpx;
  flex-shrink: 0;
}

.tree-view-wrapper {
  padding: 0 36rpx;
}

.character-tag {
  font-size: 22rpx;
  font-weight: 600;
  color: #007aff;
  background-color: rgba(0, 122, 255, 0.05);
  padding: 6rpx 20rpx;
  border-radius: 40rpx;
  border: 1px solid rgba(0, 122, 255, 0.05);
}

</style>
