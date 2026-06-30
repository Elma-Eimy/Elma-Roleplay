<template>
  <view class="detail-container" v-if="character">
    <!-- 头部导航栏 -->
    <view class="header">
      <view class="back-btn" @tap="goBack">
        <image class="back-icon" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>
      <text class="title">角色设定</text>
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
          <image 
            class="portrait-blur-bg" 
            :src="getAvatarUrl(character.avatar_path || '') || '/static/default-avatar.png'" 
            mode="aspectFill"
          />
          <!-- 前景高清立绘卡 -->
          <view class="portrait-card-wrapper">
            <image 
              class="portrait-img" 
              :src="getAvatarUrl(character.avatar_path || '') || '/static/default-avatar.png'" 
              mode="aspectFill" 
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
import { getSessions, deleteSession, updateSessionTitle, createSession, getSessionHistory } from "@/api/sessions";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import BranchTreeView from "@/components/chat/BranchTreeView.vue";
import { usePersonaStore } from "@/store/personaStore";
import CharacterProfileTab from "@/components/character/CharacterProfileTab.vue";
import CharacterLorebookTab from "@/components/character/CharacterLorebookTab.vue";

// 引入重命名分支子组件
import RenameSessionModal from "@/components/common/RenameSessionModal.vue";

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
