<template>
  <view class="page-container" :class="{ 'is-android': isAndroid }">
    <!-- 动态磨砂玻璃背景图层 -->
    <view class="chat-bg" :style="backgroundStyle"></view>

    <!-- App 端流式传输通信桥梁 (仅 APP-PLUS 环境下有效) -->
    <!-- #ifdef APP-PLUS -->
    <view :prop="chatStore.activeStreamRequest" :change:prop="stream.onStreamRequestChange" style="display: none;"></view>
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
          @longpress="onMessageLongPress"
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
          :class="{ 'is-reasoning': chatStore.useReasoning }"
          @tap="chatStore.useReasoning = !chatStore.useReasoning"
        >
          <image 
            class="reasoning-icon" 
            :src="chatStore.useReasoning ? '/static/icons/chat_sparkle_active.svg' : '/static/icons/chat_sparkle.svg'" 
            mode="aspectFit" 
          />
          <text class="reasoning-label">{{ chatStore.useReasoning ? '深度思考' : '普通模式' }}</text>
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
    />

    <!-- 向量记忆管理弹窗 -->
    <MemoryManagerModal
      :isOpen="isMemoryPanelOpen"
      :sessionId="currentSessionId"
      @close="isMemoryPanelOpen = false"
    />

    <!-- 平行时空分支树全屏遮罩面板 -->
    <view v-if="isBranchTreeOpen" class="tree-overlay-backdrop">
      <view class="tree-overlay-panel">
        <!-- 导航栏头部 -->
        <view class="custom-header border-bottom">
          <view class="header-btn left-btn" @tap="isBranchTreeOpen = false">
            <image class="back-icon" style="width: 44rpx; height: 44rpx;" src="/static/icons/drawer_close.svg" mode="aspectFit" />
          </view>
          <view class="header-center">
            <text class="character-name">时空分支树</text>
          </view>
          <view class="header-btn right-btn" style="opacity: 0; pointer-events: none;">
            <view style="width: 40rpx; height: 40rpx;"></view>
          </view>
        </view>

        <!-- 树渲染区域 -->
        <scroll-view scroll-y class="tree-scroll-area">
          <view class="tree-padding">
            <view v-if="isBranchTreeLoading" class="tree-loading">
              <text class="loading-text">正在加载平行时空...</text>
            </view>
            <BranchTreeView 
              v-else
              :sessions="sessionsList" 
              @tap-node="switchSession"
              @longpress-node="handleTreeNodeLongpress"
              @branch-node="handleTreeNodeBranch"
            />
          </view>
        </scroll-view>
      </view>
    </view>

    <!-- 新建分支故事对话框 -->
    <NewSessionModal
      :isOpen="isNewBranchModalOpen"
      :character="personaStore.activeCharacter"
      @close="isNewBranchModalOpen = false"
      @confirm="startNewBranch"
    />
  </view>
</template>

<script setup lang="ts">
// @ts-nocheck
import { ref, computed, watch } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { useChatStore } from "@/store/chatStore";
import { usePersonaStore } from "@/store/personaStore";
import { 
  createSession, 
  deleteSession, 
  getSessions, 
  updateSessionTitle, 
  getSessionHistory 
} from "@/api/sessions";
import { ChatBubble, ChatDrawer, MemoryManagerModal } from "@/components/chat";
import BranchTreeView from "@/components/chat/BranchTreeView.vue";
import NewSessionModal from "@/components/common/NewSessionModal.vue";
import { getAvatarUrl } from "@/api/characters";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { useChatScroll } from "@/composables/useChatScroll";

// 状态存储与 Composable 挂载
const chatStore = useChatStore();
const personaStore = usePersonaStore();
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
  
  await Promise.all([
    personaStore.loadSessionDetail(session.id),
    chatStore.loadHistory(session.id)
  ]);
  
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
    
    // 从后端加载该会话的详细信息与聊天历史记录
    await Promise.all([
      personaStore.loadSessionDetail(sId),
      chatStore.loadHistory(sId)
    ]);
    
    // 延迟以确保组件在端侧 DOM 挂载和计算高度完毕后再置底
    setTimeout(() => {
      scrollToBottom();
      setTimeout(() => {
        scrollWithAnimation.value = true;
        isInitLoading.value = false;
      }, 100);
    }, 250);
  }
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

const onMessageLongPress = (msg: any) => {
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
    backgroundImage: `url(${url})`
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
  } finally {
    setTimeout(() => {
      isHistoryLoading.value = false;
    }, 300);
  }
};

// App-Plus renderjs stream callbacks
const handleStreamChunk = (data: { placeholderId: string; chunk: string }) => {
  chatStore.appendStreamChunk(data.placeholderId, data.chunk);
};

const handleStreamDone = (data: { placeholderId: string; userMessageTempId?: string; meta: any }) => {
  chatStore.finalizeStream(data.placeholderId, {
    id: data.meta.assistant_message_id || Date.now(),
    role: "assistant",
    emotion_tag: data.meta.emotion_tag,
    affection_change: data.meta.affection_change,
    created_at: new Date().toISOString(),
    model_used: data.meta.model_used,
    parent_id: data.meta.user_message_id,
    is_active: true,
    candidates: data.meta.candidates,
    active_index: data.meta.active_index,
  });

  if (data.userMessageTempId) {
    const userIdx = chatStore.messages.findIndex((m) => m.tempId === data.userMessageTempId);
    if (userIdx !== -1) {
      chatStore.messages[userIdx].status = "done";
      if (data.meta.user_message_id) {
        chatStore.messages[userIdx].id = data.meta.user_message_id;
      }
    }
  }

  // 同步好感度分数与当前情绪到 Pinia Persona Store 状态库
  personaStore.applyAffectionChange(
    data.meta.affection_change,
    data.meta.affection_score,
    data.meta.emotion_tag
  );

  chatStore.isLoading = false;
  chatStore.activeStreamRequest = null;
};

const handleStreamError = (data: { placeholderId: string; userMessageTempId?: string; error: string }) => {
  chatStore.messages = chatStore.messages.filter((m) => m.tempId !== data.placeholderId);
  if (data.userMessageTempId) {
    const userIdx = chatStore.messages.findIndex((m) => m.tempId === data.userMessageTempId);
    if (userIdx !== -1) {
      chatStore.messages[userIdx].status = "error";
    }
  }
  chatStore.setError(data.error || "Failed to get AI response");
  chatStore.isLoading = false;
  chatStore.activeStreamRequest = null;
};

defineExpose({
  handleStreamChunk,
  handleStreamDone,
  handleStreamError,
});
</script>

<script module="stream" lang="renderjs">
// @ts-ignore
var abortController = null;

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
      if (abortController) {
        try {
          // @ts-ignore
          abortController.abort();
        } catch (e) {}
        // @ts-ignore
        abortController = null;
      }
    },
    // @ts-ignore
    onStreamRequestChange: function(newValue, oldValue, ownerInstance, instance) {
      if (!newValue) {
        this.abortActiveStream();
        return;
      }
      this.startStream(newValue, ownerInstance);
    },
    // @ts-ignore
    startStream: function(request, ownerInstance) {
      this.abortActiveStream();
      
      // @ts-ignore
      abortController = new AbortController();
      // @ts-ignore
      var signal = abortController.signal;
      
      var baseUrl = request.baseUrl;
      var apiKey = request.apiKey;
      var params = request.params;
      var placeholderId = request.placeholderId;
      var userMessageTempId = request.userMessageTempId;
      
      fetch(baseUrl + "/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey
        },
        body: JSON.stringify(params),
        signal: signal
      })
      .then(function(response) {
        if (!response.ok) {
          throw new Error("Server returned status code " + response.status);
        }
        if (!response.body) {
          throw new Error("ReadableStream is not supported or response body is empty");
        }

        var reader = response.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";

        function read() {
          reader.read().then(function(result) {
            if (result.done) {
              // @ts-ignore
              abortController = null;
              return;
            }

            var chunkText = decoder.decode(result.value, { stream: true });
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
                    ownerInstance.callMethod("handleStreamError", {
                      placeholderId: placeholderId,
                      userMessageTempId: userMessageTempId,
                      error: parsed.error
                    });
                  } else if (parsed.chunk !== undefined) {
                    ownerInstance.callMethod("handleStreamChunk", {
                      placeholderId: placeholderId,
                      chunk: parsed.chunk
                    });
                  } else {
                    ownerInstance.callMethod("handleStreamDone", {
                      placeholderId: placeholderId,
                      userMessageTempId: userMessageTempId,
                      meta: parsed
                    });
                  }
                } catch (e) {
                  ownerInstance.callMethod("handleStreamChunk", {
                    placeholderId: placeholderId,
                    chunk: raw
                  });
                }
              }
            }
            read(); // Recursively read next chunk
          })
          .catch(function(err) {
            if (err.name === 'AbortError') {
              return;
            }
            ownerInstance.callMethod("handleStreamError", {
              placeholderId: placeholderId,
              userMessageTempId: userMessageTempId,
              error: err.message || String(err)
            });
          });
        }
        read();
      })
      .catch(function(err) {
        if (err.name === 'AbortError') {
          return;
        }
        ownerInstance.callMethod("handleStreamError", {
          placeholderId: placeholderId,
          userMessageTempId: userMessageTempId,
          error: err.message || String(err)
        });
      });
    }
  }
}
</script>

<style scoped>
/* ===== 页面大容器 ===== */
.page-container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  background-color: #fafafa;
  position: relative;
  overflow: hidden;
}

/* 动态角色立绘背景图层 */
.chat-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-size: cover;
  background-position: center;
  opacity: 0.16; /* 提高不透明度，使角色立绘轮廓清晰可见 */
  filter: grayscale(8%) contrast(98%); /* 轻微黑白化与对比度调整，使其优雅融入背景 */
  pointer-events: none;
  z-index: 0;
}

/* 渐变遮罩：使立绘边缘自然过渡到网页/App的底色 (#fafafa) */
.chat-bg::after {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    to bottom,
    #fafafa 0%,
    transparent 12%,
    transparent 88%,
    #fafafa 100%
  );
  pointer-events: none;
}

/* ===== 自定义导航栏头部 ===== */
.custom-header {
  padding-top: env(safe-area-inset-top, 40rpx);
  height: calc(env(safe-area-inset-top, 40rpx) + 110rpx);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: 36rpx;
  padding-right: 36rpx;
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  z-index: 50;
}

.header-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.02);
}

.header-btn:active {
  background-color: rgba(0, 0, 0, 0.06);
}

.left-btn {
  margin-left: -10rpx;
}

.right-btn {
  margin-right: -10rpx;
  color: #1c1c1e;
}

.header-center {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.character-name {
  font-size: 30rpx;
  font-weight: 600;
  color: #1c1c1e;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 4rpx;
}

.status-dot {
  width: 8rpx;
  height: 8rpx;
  background-color: #34c759;
  border-radius: 50%;
}

.status-text {
  font-size: 18rpx;
  color: #8e8e93;
  font-weight: 500;
}

/* ===== 聊天内容滚动区域 ===== */
.chat-scroll-area {
  flex: 1;
  width: 100%;
  /* H5 端：scroll-view 在 flex 容器内必须有明确高度才能滚动 */
  height: 0;
  min-height: 0;
  overflow: hidden;
  position: relative;
  z-index: 1;
  background-color: transparent !important;
}

.chat-list-padding {
  padding: 24rpx 0;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.empty-chat {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-chat-text {
  color: #8e8e93;
  font-size: 26rpx;
}

/* ===== 底部对话输入区域 ===== */
.input-area-wrapper {
  position: relative;
  z-index: 10;
  background-color: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  padding: 10rpx 36rpx calc(env(safe-area-inset-bottom, 16rpx) + 14rpx) 36rpx;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.01);
}

/* ===== 深度思考切换行 ===== */
.reasoning-toggle-row {
  display: flex;
  align-items: center;
  margin-bottom: 10rpx;
}

.reasoning-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 20rpx;
  border-radius: 40rpx;
  border: 1.5px solid rgba(0, 0, 0, 0.08);
  background-color: rgba(0, 0, 0, 0.02);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
}

.reasoning-toggle-btn:active {
  transform: scale(0.95);
}

.reasoning-toggle-btn.is-reasoning {
  background-color: #1c1c1e;
  border-color: #1c1c1e;
}

.reasoning-icon {
  color: #8e8e93;
  flex-shrink: 0;
}

.reasoning-toggle-btn.is-reasoning .reasoning-icon {
  color: #f5d020;
}

.reasoning-label {
  font-size: 22rpx;
  font-weight: 500;
  color: #8e8e93;
  line-height: 1;
}

.reasoning-toggle-btn.is-reasoning .reasoning-label {
  color: #ffffff;
}

.input-area {
  display: flex;
  align-items: flex-end;
  background-color: rgba(0, 0, 0, 0.02);
  border-radius: 40rpx;
  padding: 6rpx 6rpx 6rpx 28rpx;
  border: 1px solid transparent;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.input-area.is-focused {
  background-color: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

.chat-input {
  flex: 1;
  min-height: 48rpx;
  max-height: 200rpx;
  padding: 14rpx 0;
  font-size: 28rpx;
  color: #1c1c1e;
  line-height: 1.4;
  height: auto;
}

.send-btn {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-left: 16rpx;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.send-btn.is-active {
  background-color: #1c1c1e;
}

.send-btn.is-active:active {
  transform: scale(0.92);
  background-color: #000000;
}

.send-btn.is-active .send-icon {
  /* 由于 SVG 经由 <image> 引入时，内部 currentColor 渲染默认会因为外联作用域问题降级为黑色， */
  /* 我们在这里通过 CSS 滤镜将黑色图像黑白反转为白色，实现在黑色背景上的优雅对比。 */
  filter: brightness(0) invert(1);
}

.send-icon {
  color: #ffffff;
}

/* ===== 消息编辑模态框 ===== */
.modal-backdrop {
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

.edit-modal {
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

.edit-textarea {
  width: 100%;
  height: 260rpx;
  background-color: rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: #1c1c1e;
  line-height: 1.5;
  box-sizing: border-box;
}

.edit-textarea:focus {
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
.info-icon {
  width: 40rpx;
  height: 40rpx;
}
.reasoning-icon {
  width: 26rpx;
  height: 26rpx;
}
.setting-row-icon {
  width: 40rpx;
  height: 40rpx;
}
.send-icon {
  width: 36rpx;
  height: 36rpx;
}
.close-icon {
  width: 36rpx;
  height: 36rpx;
}
.btn-icon {
  width: 32rpx;
  height: 32rpx;
}
.danger-icon {
  width: 32rpx;
  height: 32rpx;
}

/* Fallback Unicode Icon Styles */
.back-icon-fallback {
  display: none;
}
.info-icon-fallback {
  display: none;
}
.send-icon-fallback {
  display: none;
}
.reasoning-icon-fallback {
  display: none;
}
.close-icon-fallback {
  display: none;
}
.btn-icon-fallback {
  display: none;
}
.danger-icon-fallback {
  display: none;
}

/* Android Performance Fallbacks (Disable Frosted Glass) */
.is-android .custom-header {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02) !important;
}

.is-android .input-area-wrapper {
  backdrop-filter: none !important;
  background-color: #ffffff !important;
  border-top: 1px solid rgba(0, 0, 0, 0.08) !important;
}

.is-android .modal-backdrop {
  backdrop-filter: none !important;
  background-color: rgba(0, 0, 0, 0.5) !important;
}


/* ===== 平行时空分支树全屏遮罩面板样式 ===== */
.tree-overlay-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.4);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.tree-overlay-panel {
  width: 100%;
  height: 100%;
  background-color: #ffffff;
  display: flex;
  flex-direction: column;
  animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}

.border-bottom {
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.tree-scroll-area {
  flex: 1;
  width: 100%;
  height: 0;
  background-color: #fafafa;
}

.tree-padding {
  padding: 36rpx;
  padding-bottom: calc(36rpx + env(safe-area-inset-bottom, 24rpx));
}

.tree-loading {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 80rpx 0;
}

.loading-text {
  font-size: 26rpx;
  color: #8e8e93;
}

</style>

