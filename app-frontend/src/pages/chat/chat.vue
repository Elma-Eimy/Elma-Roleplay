<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 动态角色立绘背景图层（高清晰度且完整展现） -->
    <view class="chat-bg" :style="backgroundStyle"></view>

    <!-- App 端流式传输通信桥梁 (仅 APP-PLUS 环境下有效) -->
    <!-- #ifdef APP-PLUS -->
    <view :propVal="localStreamRequest" :change:propVal="stream.onStreamRequestChange" class="renderjs-bridge"></view>
    <view id="hidden-stream-bridge" style="display: none;" @bridge-msg="onBridgeMessage"></view>
    <!-- #endif -->
    <!-- 自定义导航栏头部 -->
    <view class="custom-header">
      <!-- 返回按钮 -->
      <view class="header-btn left-btn" @tap="goBack">
        <image class="back-icon" style="width: 44rpx; height: 44rpx; flex-shrink: 0;" src="/static/icons/header_back.svg" mode="aspectFit" />
      </view>

      <!-- 中部标题与角色在线状态 -->
      <view class="header-center">
        <text class="character-name">{{ personaStore.characterName || '未选角色' }}</text>
        <view class="status-indicator">
          <view class="status-dot"></view>
          <text class="status-text">{{ personaStore.currentMood || '在线' }}</text>
        </view>
      </view>

      <!-- 右侧操作栏按钮（开启信息与状态抽屉面板） -->
      <view class="header-btn right-btn" @tap="isStatusPanelOpen = true">
        <image class="info-icon" style="width: 40rpx; height: 40rpx; flex-shrink: 0;" src="/static/icons/header_info.svg" mode="aspectFit" />
      </view>
    </view>

    <!-- 聊天消息滚动区域 -->
    <scroll-view 
      class="chat-scroll-area" 
      scroll-y 
      :scroll-top="scrollTop"
      :scroll-into-view="scrollIntoViewId"
      :scroll-with-animation="scrollWithAnimation"
      @scrolltoupper="onLoadMore"
    >
      <view class="chat-list-padding">
        <ChatBubble
          v-for="msg in chatStore.messages"
          :id="msg.clientId"
          :key="msg.clientId || msg.id"
          :message="msg"
          :avatarUrl="getAvatarUrl(personaStore.activeCharacter?.avatar_path || '')"
          :characterName="personaStore.characterName"
          @longpress-message="onMessageLongPress"
        />

        <!-- 会话故事空状态 -->
        <view v-if="chatStore.messages.length === 0" class="empty-chat">
          <text class="empty-chat-text">开启新的会话故事...</text>
        </view>
      </view>
    </scroll-view>

    <!-- 底部对话输入区域 -->
    <view class="input-area-wrapper" :style="inputWrapperStyle">
      <!-- 深度思考推理模式开关行 -->
      <view class="reasoning-toggle-row">
        <view 
          class="reasoning-toggle-btn" 
          :class="{ 'is-reasoning': chatSettingsStore.useReasoning }"
          @tap="chatSettingsStore.useReasoning = !chatSettingsStore.useReasoning"
        >
          <image 
            class="reasoning-icon" 
            :src="chatSettingsStore.useReasoning ? '/static/icons/chat_sparkle_active.svg' : '/static/icons/chat_sparkle.svg'" 
            mode="aspectFit" 
          />
          <text class="reasoning-label">{{ chatSettingsStore.useReasoning ? '深度思考' : '普通模式' }}</text>
        </view>
      </view>
      <view class="input-area" :class="{ 'is-focused': isInputFocused }">
        <textarea 
          class="chat-input"
          v-model="inputText"
          placeholder="发送消息..."
          :auto-height="true"
          :maxlength="-1"
          :adjust-position="false"
          :cursor-spacing="0"
          :confirm-hold="true"
          confirm-type="send"
          @confirm="onSend"
          @focus="isInputFocused = true"
          @blur="isInputFocused = false"
          @linechange="scrollToBottom"
        />
        <view 
          class="send-btn" 
          :class="{ 'is-active': inputText.trim().length > 0 }"
          @tap="onSend"
        >
          <image class="send-icon" src="/static/icons/chat_send.svg" mode="aspectFit" />
        </view>
      </view>
      <!-- 原生软键盘占位高度（仅在 App 键盘弹起时生效），通过 flex 容器自动无缝推起并缩短上方滚动区 -->
      <view :style="{ height: keyboardHeight + 'px' }" style="transition: height 0.1s ease-out;"></view>
    </view>

    <!-- 编辑消息模态对话框 -->
    <view v-if="editingMessageId !== null" class="modal-backdrop">
      <view class="edit-modal">
        <text class="modal-title">编辑消息</text>
        <textarea 
          class="edit-textarea" 
          v-model="editMessageContent" 
          :maxlength="-1"
          :show-confirm-bar="false"
        ></textarea>
        <view class="modal-actions">
          <view class="modal-btn cancel" @tap="cancelEdit">取消</view>
          <view class="modal-btn save" @tap="saveEdit">保存</view>
        </view>
      </view>
    </view>

    <!-- 记忆与微观认知状态右侧抽屉面板 -->
    <ChatDrawer
      :isOpen="isStatusPanelOpen"
      :sessionId="currentSessionId"
      @close="isStatusPanelOpen = false"
      @delete-session="deleteCurrentSession"
      @open-branch-tree="openBranchTree"
      @open-memory-view="isMemoryPanelOpen = true"
      @open-prompt-preview="openPromptPreview"
    />

    <!-- 向量记忆管理弹窗 -->
    <MemoryManagerModal
      :isOpen="isMemoryPanelOpen"
      :sessionId="currentSessionId"
      @close="isMemoryPanelOpen = false"
    />

    <!-- 平行时空分支树全屏遮罩面板 -->
    <BranchTreePanel
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
      :isOpen="isNewBranchModalOpen"
      :character="personaStore.activeCharacter"
      @close="isNewBranchModalOpen = false"
      @confirm="startNewBranch"
    />

    <!-- 提示词预览弹窗 -->
    <PromptPreviewModal
      :isOpen="isPromptPreviewOpen"
      :messages="compiledPromptMessages"
      :tokenEstimate="compiledPromptTokenEstimate"
      @close="isPromptPreviewOpen = false"
    />
  </view>
</template>

<script setup lang="ts">
// @ts-nocheck
import { ref, computed, watch } from "vue";
import { onLoad, onUnload } from "@dcloudio/uni-app";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { useChatSettingsStore } from "@/store/chatSettingsStore";
import { 
  createSession, 
  deleteSession, 
  getSessions, 
  updateSessionTitle, 
  getSessionHistory,
  getCompiledPrompt
} from "@/api/sessions";
import { ChatBubble, ChatDrawer, MemoryManagerModal, PromptPreviewModal, BranchTreePanel } from "@/components/chat";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import { getAvatarUrl } from "@/api/characters";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { useChatScroll } from "@/composables/useChatScroll";

// 状态存储与 Composable 挂载
const chatStore = useChatStore();
const personaStore = usePersonaStore();
const chatSettingsStore = useChatSettingsStore();
const { activeAudioMessageId } = useAudioPlayer();
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

// 状态变量与视图状态
const currentSessionId = ref<number | null>(null);
const inputText = ref("");
const isInputFocused = ref(false);
const isStatusPanelOpen = ref(false);
const isMemoryPanelOpen = ref(false);
const isInitLoading = ref(true);
const isHistoryLoading = ref(false);

// 软键盘高度自适应控制样式
const inputWrapperStyle = computed(() => {
  if (keyboardHeight.value > 0) {
    return {
      paddingBottom: "14rpx",
    };
  }
  return {};
});

// 消息编辑状态
const editingMessageId = ref<number | null>(null);
const editMessageContent = ref("");

// 平行宇宙时空树的状态变量
const isBranchTreeOpen = ref(false);
const isBranchTreeLoading = ref(false);
const sessionsList = ref<any[]>([]);
const isNewBranchModalOpen = ref(false);
const activeParentSessionId = ref<number | null>(null);

// 提示词预览状态
const isPromptPreviewOpen = ref(false);
const compiledPromptMessages = ref<{ role: string; content: string }[]>([]);
const compiledPromptTokenEstimate = ref<any>(null);

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
    const res = await getSessions(personaStore.activeCharacter.id);
    const sortedSessions = res.sessions;
    const decorated = await Promise.all(
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
          }
        } catch (e) {}
        return { ...s, lastMessage: "", lastMessageTime: s.updated_at };
      })
    );
    // 按最后的消息发送时间降序排序
    decorated.sort((a, b) => new Date(b.lastMessageTime).getTime() - new Date(a.lastMessageTime).getTime());
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

const switchSession = async (session: any) => {
  isBranchTreeOpen.value = false;
  currentSessionId.value = session.id;
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

const handleTreeNodeBranch = (session: any) => {
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

const handleTreeNodeLongpress = (session: any) => {
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
              } catch (e: any) {
                uni.showToast({ title: e.message || '删除失败', icon: 'none' });
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
  localStreamRequest.value = null;
  currentStreamRequestId.value = null;
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

// 监听 Pinia Store 中的 App 端流信号，同步到组件本地变量以触发 renderjs 视图层执行
const localStreamRequest = ref<any>(null);
const currentStreamRequestId = ref<string | null>(null);
watch(() => chatStore.activeStreamRequest, (newVal) => {
  // 采用深拷贝强制更新引用，确保 value 发生引用级变化以触发 renderjs 视图层 :change:propVal 监听器
  localStreamRequest.value = newVal ? JSON.parse(JSON.stringify(newVal)) : null;
  currentStreamRequestId.value = newVal ? newVal.requestId : null;
}, { deep: true, immediate: true });

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

const onMessageLongPress = (msg: any) => {
  // 防御性检查：确保是有效的消息对象，忽略可能由冒泡触发的原生 Event 对象
  if (!msg || typeof msg !== 'object' || !msg.id || 'target' in msg) return;

  const itemList = ['复制内容', '编辑消息', '创建分支（多宇宙）', '删除此消息'];
  const isLatestAssistant = msg.id === chatStore.lastAssistantMessage?.id;
  if (msg.role === 'assistant' && isLatestAssistant) {
    itemList.splice(3, 0, '重新生成回复');
  }

  uni.showActionSheet({
    itemList,
    success: (res) => {
      const action = itemList[res.tapIndex];
      if (action === '复制内容') {
        uni.setClipboardData({
          data: msg.content,
          success: () => uni.showToast({ title: '复制成功', icon: 'none' })
        });
      } else if (action === '编辑消息') {
        editingMessageId.value = msg.id;
        editMessageContent.value = msg.content;
      } else if (action === '创建分支（多宇宙）') {
        uni.showModal({
          title: '创建分支会话',
          content: '确定要在此消息节点截断并开启一条新的分支故事会话吗？',
          confirmColor: '#10b981',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm && currentSessionId.value !== null) {
              try {
                uni.showLoading({ title: '正在创建分支...' });
                const branchRes = await createSession({
                  character_id: personaStore.activeCharacter!.id,
                  parent_session_id: currentSessionId.value,
                  title: `${personaStore.activeCharacter!.name} (分支故事)`,
                  start_message_id: msg.id
                });
                uni.hideLoading();
                uni.showToast({ title: '分支创建成功', icon: 'success' });
                
                setTimeout(() => {
                  uni.redirectTo({
                    url: `/pages/chat/chat?sessionId=${branchRes.session_id}`
                  });
                }, 1000);
              } catch (e) {
                uni.hideLoading();
                console.error(e);
                uni.showToast({ title: '创建分支失败', icon: 'none' });
              }
            }
          }
        });
      } else if (action === '删除此消息') {
        uni.showModal({
          title: '删除消息',
          content: '确定要删除此消息吗？',
          confirmColor: '#ff3b30',
          cancelColor: '#8e8e93',
          success: async (mRes) => {
            if (mRes.confirm) {
              await chatStore.deleteMessageById(msg.id);
            }
          }
        });
      } else if (action === '重新生成回复') {
        if (currentSessionId.value !== null) {
          (async () => {
            try {
              await chatStore.regenerateChatMessage(currentSessionId.value!);
              scrollToBottom();
            } catch (e) {
              console.error("Failed to regenerate response", e);
            }
          })();
        }
      }
    }
  });
};

const cancelEdit = () => {
  editingMessageId.value = null;
  editMessageContent.value = "";
};

const saveEdit = async () => {
  if (editingMessageId.value !== null) {
    await chatStore.editMessage(editingMessageId.value, editMessageContent.value);
    cancelEdit();
  }
};

// 聊天背景图样式
const backgroundStyle = computed(() => {
  const avatar = personaStore.activeCharacter?.avatar_path;
  if (!avatar) return {};
  const url = getAvatarUrl(avatar);
  return {
    backgroundImage: `url('${url}')`
  };
});



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

// App-Plus renderjs stream callbacks using native DOM Event Bridge
const onBridgeMessage = (e: any) => {
  try {
    const payload = e.detail;
    if (!payload) return;
    console.log("[Vue Logic] onBridgeMessage received type:", payload.type);
    
    // 如果是流相关的消息类型，安全拦截校验 requestId，防止跨页面/孤儿请求导致的状态冲突与卡死
    if (payload.type === "chunk" || payload.type === "reasoning_chunk" || payload.type === "done" || payload.type === "error") {
      if (payload.requestId !== currentStreamRequestId.value) {
        console.warn(`[Vue Logic] Discarding orphaned stream event of type: ${payload.type}. Request ID mismatch.`);
        return;
      }
    }
    
    if (payload.type === "chunk") {
      chatStore.appendStreamChunk(payload.placeholderId, payload.chunk);
    } else if (payload.type === "reasoning_chunk") {
      chatStore.appendStreamReasoningChunk(payload.placeholderId, payload.reasoning_chunk);
    } else if (payload.type === "done") {
      // 提取后端入库的完整 Ground-Truth 文本以防止字符缺失，并对 meta 加以防护，防止 undefined 属性解构异常
      const meta = payload.meta || {};
      const candidates = meta.candidates || [];
      const activeIndex = meta.active_index ?? (candidates.length - 1);
      const finalContent = candidates[activeIndex]?.content;

      chatStore.finalizeStream(payload.placeholderId, {
        id: meta.assistant_message_id || Date.now(),
        role: "assistant",
        ...(finalContent ? { content: finalContent } : {}),
        emotion_tag: meta.emotion_tag,
        affection_change: meta.affection_change,
        created_at: new Date().toISOString(),
        model_used: meta.model_used,
        parent_id: meta.user_message_id,
        is_active: true,
        candidates: meta.candidates,
        active_index: meta.active_index,
      });

      if (payload.userMessageTempId) {
        const userIdx = chatStore.messages.findIndex((m) => m.tempId === payload.userMessageTempId);
        if (userIdx !== -1) {
          chatStore.messages[userIdx].status = "done";
          if (meta.user_message_id) {
            chatStore.messages[userIdx].id = meta.user_message_id;
          }
        }
      }

      // 同步好感度分数与当前情绪到 Pinia Persona Store 状态库
      personaStore.applyAffectionChange(
        meta.affection_change,
        meta.affection_score,
        meta.emotion_tag
      );

      chatStore.isLoading = false;
      chatStore.activeStreamRequest = null;
    } else if (payload.type === "error") {
      chatStore.messages = chatStore.messages.filter((m) => m.tempId !== payload.placeholderId);
      if (payload.userMessageTempId) {
        const userIdx = chatStore.messages.findIndex((m) => m.tempId === payload.userMessageTempId);
        if (userIdx !== -1) {
          chatStore.messages[userIdx].status = "error";
        }
      }
      chatStore.setError(payload.error || "Failed to get AI response");
      uni.showToast({ title: payload.error || "获取回复失败", icon: "none" });
      chatStore.isLoading = false;
      chatStore.activeStreamRequest = null;
    } else if (payload.type === "log") {
      if (payload.level === "error") {
        console.error(`[WebView Log][error]`, payload.message);
      } else if (payload.level === "warn") {
        console.warn(`[WebView Log][warn]`, payload.message);
      } else {
        console.log(`[WebView Log][info]`, payload.message);
      }
    }
  } catch (err) {
    console.error("[Vue Logic] onBridgeMessage parse error:", err);
  }
};
</script>

<script module="stream" lang="renderjs">
// @ts-ignore
var activeXhr = null;

function sendToLogic(type, payload) {
  var bridgeEl = document.getElementById("hidden-stream-bridge");
  if (bridgeEl) {
    var data = { type: type };
    for (var key in payload) {
      data[key] = payload[key];
    }
    
    var evt;
    if (typeof CustomEvent === "function") {
      evt = new CustomEvent("bridge-msg", {
        detail: data,
        bubbles: true,
        cancelable: true
      });
    } else {
      evt = document.createEvent("CustomEvent");
      evt.initCustomEvent("bridge-msg", true, true, data);
    }
    
    bridgeEl.dispatchEvent(evt);
  } else {
    console.error("[renderjs] hidden-stream-bridge element not found!");
  }
}

export default {
  beforeDestroy: function() {
    this.abortActiveStream();
  },
  beforeUnmount: function() {
    this.abortActiveStream();
  },
  methods: {
    abortActiveStream: function() {
      // @ts-ignore
      if (activeXhr) {
        try {
          // @ts-ignore
          activeXhr.abort();
        } catch (e) {}
        // @ts-ignore
        activeXhr = null;
      }
    },
    // @ts-ignore
    onStreamRequestChange: function(newValue, oldValue, ownerInstance, instance) {
      var logMsg = "[renderjs] onStreamRequestChange triggered. newValue: " + JSON.stringify(newValue);
      console.log(logMsg);
      sendToLogic("log", { level: "info", message: logMsg });

      if (!newValue) {
        this.abortActiveStream();
        return;
      }
      this.startStream(newValue, ownerInstance);
    },
    // @ts-ignore
    startStream: function(request, ownerInstance) {
      try {
        var logMsg = "[renderjs] startStream entered. placeholder: " + request.placeholderId;
        console.log(logMsg);
        sendToLogic("log", { level: "info", message: logMsg });

        this.abortActiveStream();
        
        var requestId = request.requestId;
        var baseUrl = request.baseUrl;
        var apiKey = request.apiKey;
        var params = request.params;
        var placeholderId = request.placeholderId;
        var userMessageTempId = request.userMessageTempId;
        
        // 包装 sendToLogic 函数，自动将 requestId 注入到 payload 中，实现跨页面安全隔离与防卡死
        function sendToLogicWithReq(type, payload) {
          var payloadData = payload || {};
          payloadData.requestId = requestId;
          sendToLogic(type, payloadData);
        }
        
        var fetchUrl = baseUrl + "/chat/stream";
        var logUrlMsg = "[renderjs] XHR url: " + fetchUrl;
        console.log(logUrlMsg);
        sendToLogic("log", { level: "info", message: logUrlMsg });
        
        var xhr = new XMLHttpRequest();
        // @ts-ignore
        activeXhr = xhr;
        
        xhr.open("POST", fetchUrl, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        if (apiKey) {
          xhr.setRequestHeader("X-API-Key", apiKey);
        }
        
        var lastSeenIndex = 0;
        var buffer = "";
        
        function handleChunk(chunkText) {
          buffer += chunkText;
          var lines = buffer.split("\n");
          buffer = lines.pop() || "";
          
          for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var trimmedLine = line.trim();
            if (!trimmedLine) continue;
            
            if (trimmedLine.indexOf("data: ") === 0) {
              var raw = trimmedLine.slice(6).trim();
              if (raw === "[DONE]") {
                continue;
              }
              try {
                var parsed = JSON.parse(raw);
                if (parsed.error !== undefined) {
                  var logErrorMsg = "[renderjs] stream error chunk parsed: " + parsed.error;
                  console.log(logErrorMsg);
                  sendToLogic("log", { level: "warn", message: logErrorMsg });
                  
                  sendToLogicWithReq("error", {
                    placeholderId: placeholderId,
                    userMessageTempId: userMessageTempId,
                    error: parsed.error
                  });
                } else if (parsed.reasoning_chunk !== undefined) {
                  sendToLogicWithReq("reasoning_chunk", {
                    placeholderId: placeholderId,
                    reasoning_chunk: parsed.reasoning_chunk
                  });
                } else if (parsed.chunk !== undefined) {
                  sendToLogicWithReq("chunk", {
                    placeholderId: placeholderId,
                    chunk: parsed.chunk
                  });
                } else {
                  var logMetaMsg = "[renderjs] stream metadata done chunk: " + JSON.stringify(parsed);
                  console.log(logMetaMsg);
                  sendToLogic("log", { level: "info", message: logMetaMsg });
                  
                  sendToLogicWithReq("done", {
                    placeholderId: placeholderId,
                    userMessageTempId: userMessageTempId,
                    meta: parsed
                  });
                }
              } catch (e) {
                sendToLogicWithReq("chunk", {
                  placeholderId: placeholderId,
                  chunk: raw
                });
              }
            }
          }
        }
        
        xhr.onprogress = function() {
          try {
            var responseText = xhr.responseText;
            var newData = responseText.substring(lastSeenIndex);
            lastSeenIndex = responseText.length;
            if (newData) {
              handleChunk(newData);
            }
          } catch (e) {
            console.error("[renderjs] onprogress error", e);
          }
        };
        
        xhr.onload = function() {
          try {
            var responseText = xhr.responseText;
            var newData = responseText.substring(lastSeenIndex);
            if (newData) {
              handleChunk(newData);
            }
            if (buffer.trim()) {
              handleChunk("\n");
            }
            // @ts-ignore
            activeXhr = null;
          } catch (e) {}
        };
        
        xhr.onerror = function(err) {
          var logErrorMsg = "[renderjs] XHR error caught";
          console.error(logErrorMsg);
          sendToLogic("log", { level: "error", message: logErrorMsg });
          
          sendToLogicWithReq("error", {
            placeholderId: placeholderId,
            userMessageTempId: userMessageTempId,
            error: "网络连接失败或服务器响应异常"
          });
          // @ts-ignore
          activeXhr = null;
        };
        
        xhr.send(JSON.stringify(params));
        
      } catch (globalErr) {
        var logGlobalErrorMsg = "[renderjs] startStream global error caught: " + (globalErr.message || String(globalErr));
        console.error(logGlobalErrorMsg);
        sendToLogic("log", { level: "error", message: logGlobalErrorMsg });

        // 避免在 catch 中调用 try 作用域内的 sendToLogicWithReq 导致 ReferenceError，直接使用 sendToLogic 并拼接参数
        sendToLogic("error", {
          requestId: request ? request.requestId : undefined,
          placeholderId: request ? request.placeholderId : undefined,
          userMessageTempId: request ? request.userMessageTempId : undefined,
          error: globalErr.message || String(globalErr)
        });
        // @ts-ignore
        activeXhr = null;
      }
    }
  }
}
</script>

<style scoped src="./chat.css"></style>
