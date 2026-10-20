<template>
  <view class="page-container app-motion-enter" :class="{ 'is-android': isAndroid }">
    <view
      class="chat-bg"
      :class="`mode-${backgroundMode}`"
      :style="backgroundStyle"
    >
      <image
        v-if="backgroundMode === 'character' && characterBackgroundUrl"
        class="chat-scene-image"
        :src="characterBackgroundUrl"
        mode="aspectFill"
      />
    </view>

    <!-- App 端流式传输通信桥梁 (仅 APP-PLUS 环境下有效) -->
    <!-- #ifdef APP-PLUS -->
    <ChatStreamBridge :request="localStreamRequest" @message="onBridgeMessage" />
    <!-- #endif -->
    <ChatHeader
      :character-name="personaStore.characterName"
      :current-mood="personaStore.currentMood"
      :is-android="isAndroid"
      @back="goBack"
      @open-status="isStatusPanelOpen = true"
    />

    <ChatMessageList
      :messages="chatStore.messages"
      :avatar-url="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
      :character-name="personaStore.characterName"
      :scroll-top="scrollTop"
      :scroll-into-view-id="scrollIntoViewId"
      :scroll-with-animation="scrollWithAnimation"
      @load-more="onLoadMore"
      @longpress-message="onMessageLongPress"
    />

    <ChatComposer
      v-model="inputText"
      :use-reasoning="chatSettingsStore.useReasoning"
      :is-focused="isInputFocused"
      :is-android="isAndroid"
      :keyboard-height="keyboardHeight"
      :wrapper-style="inputWrapperStyle"
      @update:use-reasoning="chatSettingsStore.useReasoning = $event"
      @focus-change="isInputFocused = $event"
      @line-change="scrollToBottom"
      @send="onSend"
    />

    <EditMessageModal
      v-model="editMessageContent"
      :is-open="editingMessageId !== null"
      :is-android="isAndroid"
      @cancel="cancelEdit"
      @save="saveEdit"
    />

    <!-- 记忆与微观认知状态右侧抽屉面板 -->
    <ChatDrawer
      v-if="isStatusPanelOpen"
      :isOpen="isStatusPanelOpen"
      :sessionId="currentSessionId"
      :background-mode="backgroundMode"
      @close="isStatusPanelOpen = false"
      @update:background-mode="updateBackgroundMode"
      @delete-session="deleteCurrentSession"
      @open-branch-tree="openBranchTree"
      @open-memory-view="isMemoryPanelOpen = true"
      @open-prompt-preview="openPromptPreview"
    />

    <!-- 向量记忆管理弹窗 -->
    <MemoryManagerModal
      v-if="isMemoryPanelOpen"
      :isOpen="isMemoryPanelOpen"
      :sessionId="currentSessionId"
      @close="isMemoryPanelOpen = false"
    />

    <!-- 平行时空分支树全屏遮罩面板 -->
    <BranchTreePanel
      v-if="isBranchTreeOpen"
      :isOpen="isBranchTreeOpen"
      :isLoading="isBranchTreeLoading"
      :sessions="sessionsList"
      @close="isBranchTreeOpen = false"
      @tap-node="switchSession"
      @longpress-node="handleTreeNodeLongpress"
      @branch-node="handleTreeNodeBranch"
    />

    <!-- 新建分支故事对话框 -->
    <NewSessionModal
      v-if="isNewBranchModalOpen"
      :isOpen="isNewBranchModalOpen"
      :character="personaStore.activeCharacter"
      :character-id="personaStore.activeCharacter?.id"
      :character-name="personaStore.characterName"
      @close="isNewBranchModalOpen = false"
      @confirm="startNewBranch"
    />

    <!-- 提示词预览弹窗 -->
    <PromptPreviewModal
      v-if="isPromptPreviewOpen"
      :isOpen="isPromptPreviewOpen"
      :messages="compiledPromptMessages"
      :tokenEstimate="compiledPromptTokenEstimate"
      @close="isPromptPreviewOpen = false"
    />
  </view>
</template>

<script setup lang="ts">
// #ifdef APP-PLUS
import ChatStreamBridge from "@/components/chat/ChatStreamBridge.vue";
// #endif
import { ref, computed, watch } from "vue";
import { onLoad, onUnload } from "@dcloudio/uni-app";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { 
  createSession, 
  deleteSession, 
  getAllSessions,
  updateSessionTitle, 
  getCompiledPrompt
} from "@/api/sessions";
import ChatHeader from "@/components/chat/ChatHeader.vue";
import ChatMessageList from "@/components/chat/ChatMessageList.vue";
import ChatComposer from "@/components/chat/ChatComposer.vue";
import EditMessageModal from "@/components/chat/EditMessageModal.vue";
import ChatDrawer from "@/components/chat/ChatDrawer.vue";
import MemoryManagerModal from "@/components/chat/MemoryManagerModal.vue";
import PromptPreviewModal from "@/components/chat/PromptPreviewModal.vue";
import BranchTreePanel from "@/components/chat/BranchTreePanel.vue";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import { getAvatarUrl } from "@/api/characters";
import { useChatScroll } from "@/composables/useChatScroll";
import { useChatStreamBridge } from "@/composables/useChatStreamBridge";
import { useChatMessageActions } from "@/composables/useChatMessageActions";
import type { TokenEstimate } from "@/api/sessions";
import type { BranchSession } from "@/types/chat";

// 状态存储与 Composable 挂载
const chatStore = useChatStore();
const personaStore = usePersonaStore();
const chatSettingsStore = useChatSettingsStore();
const {
  scrollTop,
  scrollIntoViewId,
  scrollWithAnimation,
  keyboardHeight,
  isAndroid,
  scrollToBottom,
  scrollToBottomThrottled,
  triggerPhasedScroll,
  maintainScrollPosition,
} = useChatScroll();
const {
  localStreamRequest,
  onBridgeMessage,
  resetStreamBridge,
} = useChatStreamBridge();

// 状态变量与视图状态
const currentSessionId = ref<number | null>(null);
const inputText = ref("");
const isInputFocused = ref(false);
const isStatusPanelOpen = ref(false);
const isMemoryPanelOpen = ref(false);
const isInitLoading = ref(true);
const isHistoryLoading = ref(false);
type ChatBackgroundMode = "clean" | "character";

const CHAT_BACKGROUND_STORAGE_PREFIX = "chat_background_mode:";
const backgroundMode = ref<ChatBackgroundMode>("clean");

const getBackgroundStorageKey = (sessionId: number) =>
  `${CHAT_BACKGROUND_STORAGE_PREFIX}${sessionId}`;

const readBackgroundMode = (sessionId: number): ChatBackgroundMode => {
  try {
    return uni.getStorageSync(getBackgroundStorageKey(sessionId)) === "character"
      ? "character"
      : "clean";
  } catch {
    return "clean";
  }
};

const saveBackgroundMode = (
  sessionId: number,
  mode: ChatBackgroundMode
) => {
  try {
    uni.setStorageSync(getBackgroundStorageKey(sessionId), mode);
  } catch (error) {
    console.warn("[chat.vue] Failed to save chat background preference:", error);
  }
};

const clearBackgroundMode = (sessionId: number) => {
  try {
    uni.removeStorageSync(getBackgroundStorageKey(sessionId));
  } catch (error) {
    console.warn("[chat.vue] Failed to clear chat background preference:", error);
  }
};

const updateBackgroundMode = (mode: ChatBackgroundMode) => {
  backgroundMode.value = mode;
  if (currentSessionId.value !== null) {
    saveBackgroundMode(currentSessionId.value, mode);
  }
};

// 软键盘高度自适应控制样式
const inputWrapperStyle = computed(() => {
  if (keyboardHeight.value > 0) {
    return {
      paddingBottom: "14rpx",
    };
  }
  return {};
});

const {
  editingMessageId,
  editMessageContent,
  onMessageLongPress,
  cancelEdit,
  saveEdit,
} = useChatMessageActions(currentSessionId, scrollToBottom);

// 平行宇宙时空树的状态变量
const isBranchTreeOpen = ref(false);
const isBranchTreeLoading = ref(false);
const sessionsList = ref<BranchSession[]>([]);
const isNewBranchModalOpen = ref(false);
const activeParentSessionId = ref<number | null>(null);

// 提示词预览状态
const isPromptPreviewOpen = ref(false);
const compiledPromptMessages = ref<{ role: string; content: string }[]>([]);
const compiledPromptTokenEstimate = ref<TokenEstimate | null>(null);

const openPromptPreview = async () => {
  isStatusPanelOpen.value = false;
  if (currentSessionId.value === null) return;
  try {
    uni.showLoading({ title: "正在组装提示词..." });
    const res = await getCompiledPrompt(currentSessionId.value);
    compiledPromptMessages.value = res.messages;
    compiledPromptTokenEstimate.value = res.token_estimate || null;
    isPromptPreviewOpen.value = true;
  } catch (e) {
    console.error("Failed to load compiled prompt", e);
    uni.showToast({ title: "获取提示词失败", icon: "none" });
  } finally {
    uni.hideLoading();
  }
};

const loadSessionsList = async () => {
  if (!personaStore.activeCharacter) return;
  isBranchTreeLoading.value = true;
  try {
    const res = await getAllSessions(personaStore.activeCharacter.id);
    const decorated = res.sessions.map((session) => ({
      ...session,
      lastMessage: session.last_message?.content
        ? session.last_message.content.replace(/\s+/g, " ").trim()
        : "",
      lastMessageTime: session.last_message?.created_at || session.updated_at
    }));
    sessionsList.value = decorated;
  } catch (e) {
    console.error("Failed to load sessions for character", e);
  } finally {
    isBranchTreeLoading.value = false;
  }
};

const openBranchTree = async () => {
  isStatusPanelOpen.value = false;
  isBranchTreeOpen.value = true;
  await loadSessionsList();
};

const switchSession = async (session: Pick<BranchSession, "id">) => {
  isBranchTreeOpen.value = false;
  currentSessionId.value = session.id;
  backgroundMode.value = readBackgroundMode(session.id);
  isInitLoading.value = true;
  scrollWithAnimation.value = false;
  
  try {
    await Promise.all([
      personaStore.loadSessionDetail(session.id),
      chatStore.loadHistory(session.id)
    ]);
  } catch (err) {
    console.error("[chat.vue] switchSession Promise.all failed with error:", err);
  }
  
  setTimeout(() => {
    scrollToBottom();
    setTimeout(() => {
      scrollWithAnimation.value = true;
    }, 100);
  }, 100);
  isInitLoading.value = false;
};

const handleTreeNodeBranch = (session: Pick<BranchSession, "id">) => {
  activeParentSessionId.value = session.id;
  isNewBranchModalOpen.value = true;
};

const startNewBranch = async (payload: { title: string; greeting_index: number | null }) => {
  if (!personaStore.activeCharacter) return;
  try {
    uni.showLoading({ title: '正在开启故事...' });
    const res = await createSession({
      character_id: personaStore.activeCharacter.id,
      parent_session_id: activeParentSessionId.value,
      title: payload.title,
      greeting_index: payload.greeting_index !== null ? payload.greeting_index : undefined
    });
    if (activeParentSessionId.value !== null) {
      saveBackgroundMode(
        res.session_id,
        readBackgroundMode(activeParentSessionId.value)
      );
    }
    uni.hideLoading();
    isNewBranchModalOpen.value = false;
    // 闪切到新创建的平行宇宙会话
    await switchSession({ id: res.session_id });
    uni.showToast({ title: '已跳转至新平行宇宙', icon: 'success' });
  } catch (e) {
    uni.hideLoading();
    uni.showToast({ title: '开启新平行故事失败', icon: 'none' });
  }
};

const handleTreeNodeLongpress = (session: BranchSession) => {
  uni.vibrateShort({ success: () => {} });
  uni.showActionSheet({
    itemList: ['重命名分支', '删除分支'],
    success: async (actionRes) => {
      if (actionRes.tapIndex === 0) {
        // 重命名
        uni.showModal({
          title: '重命名分支',
          editable: true,
          placeholderText: '请输入新标题',
          content: session.title,
          success: async (modalRes) => {
            if (modalRes.confirm && modalRes.content?.trim()) {
              try {
                await updateSessionTitle(session.id, modalRes.content.trim());
                await loadSessionsList();
                uni.showToast({ title: '重命名成功', icon: 'success' });
              } catch (e) {
                uni.showToast({ title: '重命名失败', icon: 'none' });
              }
            }
          }
        });
      } else if (actionRes.tapIndex === 1) {
        // 删除
        uni.showModal({
          title: '删除宇宙分支',
          content: '确定要删除此平行世界故事线吗？该人格的所有记忆将被抹去。',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (modalRes) => {
            if (modalRes.confirm) {
              try {
                await deleteSession(session.id);
                clearBackgroundMode(session.id);
                // 如果删除的是当前会话，需要退回到会话列表首页
                if (session.id === currentSessionId.value) {
                  uni.showToast({ title: '当前会话已删除', icon: 'none' });
                  setTimeout(() => {
                    uni.switchTab({ url: "/pages/index/index" });
                  }, 1500);
                } else {
                  await loadSessionsList();
                  uni.showToast({ title: '删除成功', icon: 'success' });
                }
              } catch (error) {
                const message = error instanceof Error ? error.message : "删除失败";
                uni.showToast({ title: message, icon: 'none' });
              }
            }
          }
        });
      }
    }
  });
};

// 监听输入框焦点以触底滚动
watch(isInputFocused, (focused) => {
  if (focused) {
    triggerPhasedScroll();
  }
});

onLoad(async (options) => {
  if (options && options.sessionId) {
    const sId = parseInt(options.sessionId, 10);
    currentSessionId.value = sId;
    backgroundMode.value = readBackgroundMode(sId);
    
    isInitLoading.value = true;
    scrollWithAnimation.value = false;
    
    try {
      await Promise.all([
        personaStore.loadSessionDetail(sId),
        chatStore.loadHistory(sId)
      ]);
    } catch (err) {
      console.error("[chat.vue] Promise.all failed with error:", err);
    }
    
    // 延迟以确保组件在端侧 DOM 挂载和计算高度完毕后再置底
    setTimeout(() => {
      scrollToBottom();
      setTimeout(() => {
        scrollWithAnimation.value = true;
        isInitLoading.value = false;
      }, 100);
    }, 250);
  } else {
    console.warn("[chat.vue] onLoad triggered but options.sessionId is missing or empty!");
  }
});

onUnload(() => {
  console.log("[chat.vue] onUnload page - resetting chatStore");
  chatStore.$reset();
  personaStore.cancelSessionLoad();
  resetStreamBridge();
});

const goBack = () => {
  const pages = getCurrentPages();
  if (pages.length > 1) {
    uni.navigateBack();
  } else {
    uni.switchTab({
      url: "/pages/index/index"
    });
  }
};

// 监听消息长度变化以自动置底
watch(() => chatStore.messages.length, () => {
  if (isInitLoading.value || isHistoryLoading.value) return;
  scrollToBottom();
});

// 流式输出时，使用节流控制置底并临时关闭动画以防卡顿
watch(() => chatStore.streamingText, () => {
  if (isInitLoading.value) return;
  scrollWithAnimation.value = false;
  scrollToBottomThrottled();
});

// 对话彻底结束或状态变动时置底
watch(() => chatStore.isLoading, (loading) => {
  if (isInitLoading.value || isHistoryLoading.value) return;
  if (!loading) {
    scrollWithAnimation.value = true;
    scrollToBottom();
  }
});

const onSend = async () => {
  const text = inputText.value.trim();
  if (!text || chatStore.isLoading || currentSessionId.value === null) return;

  inputText.value = "";
  chatStore.sendChatMessage(currentSessionId.value, text);
  scrollToBottom();
};

// 角色柔光主题：不直接展示全屏立绘，仅以稳定的淡色气氛区分角色。
const chatGlowPalettes = [
  {
    primary: "rgba(112, 174, 155, 0.2)",
    secondary: "rgba(139, 184, 220, 0.13)",
  },
  {
    primary: "rgba(139, 184, 220, 0.2)",
    secondary: "rgba(241, 201, 141, 0.12)",
  },
  {
    primary: "rgba(241, 201, 141, 0.19)",
    secondary: "rgba(112, 174, 155, 0.12)",
  },
];

const backgroundStyle = computed(() => {
  const characterId = personaStore.activeCharacter?.id || 0;
  const palette = chatGlowPalettes[
    Math.abs(characterId) % chatGlowPalettes.length
  ];
  return {
    "--chat-glow-primary": palette.primary,
    "--chat-glow-secondary": palette.secondary,
  };
});

const characterBackgroundUrl = computed(() =>
  getAvatarUrl(personaStore.activeCharacter?.avatar_path || "")
);



// 删除当前会话
const deleteCurrentSession = () => {
  if (currentSessionId.value === null) return;
  uni.showModal({
    title: '删除会话',
    content: '确定要删除此会话吗？所有聊天记录与记忆数据将无法找回。',
    confirmColor: '#ff3b30',
    cancelColor: '#8e8e93',
    success: async (res) => {
      if (res.confirm) {
        try {
          uni.showLoading({ title: '正在删除...' });
          await deleteSession(currentSessionId.value!);
          clearBackgroundMode(currentSessionId.value!);
          uni.hideLoading();
          isStatusPanelOpen.value = false;
          uni.navigateBack();
        } catch (e) {
          uni.hideLoading();
          uni.showToast({ title: '删除失败，请重试', icon: 'none' });
          console.error(e);
        }
      }
    }
  });
};

const onLoadMore = async () => {
  if (chatStore.isLoading || chatStore.messages.length === 0) return;
  
  isHistoryLoading.value = true;
  try {
    const oldestMsg = chatStore.messages[0];
    const oldestClientId = oldestMsg ? oldestMsg.clientId : null;
    
    const hasMore = await chatStore.loadMoreHistory();
    if (hasMore && oldestClientId) {
      await maintainScrollPosition(oldestClientId);
    }
  } catch (err) {
    console.error("[chat.vue] onLoadMore failed with exception:", err);
  } finally {
    setTimeout(() => {
      isHistoryLoading.value = false;
    }, 300);
  }
};

</script>

<style scoped src="./chat.css"></style>
