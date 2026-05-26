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
          />
          <view class="portrait-overlay"></view>
          
          <view class="change-portrait-btn" @tap="changePortrait">
            <image class="change-portrait-icon" src="/static/icons/char_camera.svg" mode="aspectFit" />
            <text class="change-portrait-text">更换立绘</text>
          </view>
        </view>

        <!-- 角色基本名称与标签区域 -->
        <view class="char-header-section">
          <text class="char-name">{{ character.name }}</text>
          <view class="tag-row" v-if="character.personality">
            <view 
              class="personality-tag" 
              v-for="tag in personalityTags" 
              :key="tag"
            >
              {{ tag }}
            </view>
          </view>
        </view>

        <!-- 角色背景描述卡片 -->
        <view class="section-card">
          <text class="section-title">人设背景描述</text>
          <scroll-view scroll-y class="section-scroll-container">
            <rich-text class="section-body" :nodes="renderedDescription" />
          </scroll-view>
        </view>

        <view class="section-card" v-if="character.scenario">
          <text class="section-title">所处场景环境</text>
          <scroll-view scroll-y class="section-scroll-container">
            <rich-text class="section-body" :nodes="renderedScenario" />
          </scroll-view>
        </view>

        <view class="section-card" v-if="character.first_mes">
          <text class="section-title">开场白预设</text>
          <scroll-view scroll-y class="section-scroll-container">
            <rich-text class="section-body italic" :nodes="renderedFirstMes" />
          </scroll-view>
        </view>

        <!-- 多重平行故事宇宙（衍生会话分支） -->
        <view class="branches-header">
          <text class="branches-title">衍生故事宇宙 (平行世界)</text>
        </view>

        <view class="branches-list">
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
                  <text class="meta-value score">{{ session.persona?.affection_score || 0 }} 💖</text>
                </view>
              </view>
            </view>
            <text class="branch-preview">{{ session.lastMessage || '尚无对话记录...' }}</text>
            <text class="branch-date">{{ formatDate(session.updated_at) }}</text>
          </view>

          <!-- 平行宇宙分支空状态 -->
          <view v-if="sessions.length === 0" class="empty-branches">
            <text class="empty-branches-text">尚未开启任何故事宇宙。点击下方开启平行世界。</text>
          </view>
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
import MarkdownIt from "markdown-it";

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
});

const characterId = ref<number | null>(null);
const character = ref<CharacterDetail | null>(null);
const sessions = ref<any[]>([]);
const isNewBranchModalOpen = ref(false);

const renamingSessionId = ref<number | null>(null);
const newSessionTitle = ref("");
const activeParentSessionId = ref<number | null>(null);

const getParentSessionTitle = (parentId: number | null) => {
  if (!parentId) return "";
  const parent = sessions.value.find(s => s.id === parentId);
  return parent ? parent.title : `会话 #${parentId}`;
};

const personalityTags = computed(() => {
  if (!character.value?.personality) return [];
  return character.value.personality.split(/[,，\s]+/).filter(tag => tag.trim() !== "");
});

const renderedDescription = computed(() => {
  const content = character.value?.description || "";
  if (!content) return "";
  let html = md.render(content);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  return html;
});

const renderedScenario = computed(() => {
  const content = character.value?.scenario || "";
  if (!content) return "";
  let html = md.render(content);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  return html;
});

const renderedFirstMes = computed(() => {
  const content = character.value?.first_mes || "";
  if (!content) return "";
  let html = md.render(content);
  html = html.replace(/<p>/g, '<p class="md-p">');
  html = html.replace(/<em>/g, '<em class="md-em">');
  html = html.replace(/<strong>/g, '<strong class="md-strong">');
  return html;
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
          const lastMsg = hRes.messages.length > 0 
            ? hRes.messages[hRes.messages.length - 1].content 
            : "";
          const cleanMsg = lastMsg ? lastMsg.replace(/\s+/g, ' ').trim() : "";
          return { ...s, lastMessage: cleanMsg };
        } catch (e) {
          return { ...s, lastMessage: "" };
        }
      })
    );

    // 按更新时间降序对分支会话进行排序
    decoratedSessions.sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
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

const startNewBranch = async (title: string) => {
  if (characterId.value === null) return;
  try {
    uni.showLoading({ title: '正在开启故事...' });
    const res = await createSession({
      character_id: characterId.value,
      parent_session_id: activeParentSessionId.value,
      title
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
        uni.showModal({
          title: '删除宇宙分支',
          content: '确定要删除此平行世界故事线吗？该人格的所有记忆将被抹去。',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm && characterId.value !== null) {
              try {
                await deleteSession(session.id);
                await loadCharacterData(characterId.value);
              } catch (e) {
                console.error("Failed to delete branch", e);
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
  height: 420rpx;
  background-color: #f2f2f7;
  overflow: hidden;
}

.portrait-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.portrait-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 140rpx;
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

/* ===== 设定描述卡片 ===== */
.section-card {
  margin: 0 36rpx 28rpx 36rpx;
  background-color: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 24rpx;
  padding: 32rpx;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.01);
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.section-title {
  font-size: 24rpx;
  font-weight: 600;
  color: #8e8e93;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-scroll-container {
  min-height: 80rpx;
  max-height: 450rpx;
  width: 100%;
  box-sizing: border-box;
  padding-right: 12rpx;
}

.section-scroll-container ::-webkit-scrollbar {
  width: 4px;
}

.section-scroll-container ::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 2px;
}

.section-body {
  font-size: 28rpx;
  color: #2c2c2e;
  line-height: 1.6;
}

.section-body :deep(.md-p) {
  margin: 10rpx 0;
  line-height: 1.6;
}

.section-body :deep(.md-strong) {
  font-weight: 600;
  color: #000000;
  padding: 0 4rpx;
}

.section-body :deep(.md-em) {
  font-style: italic;
  color: #3a3a3c;
  padding: 0 4rpx;
}

.section-body.italic {
  font-style: italic;
  color: #48484a;
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
  font-size: 28rpx;
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
  font-size: 20rpx;
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
  font-size: 20rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.03);
  padding: 4rpx 12rpx;
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
  font-size: 26rpx;
  color: #8e8e93;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.branch-date {
  font-size: 20rpx;
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
</style>
