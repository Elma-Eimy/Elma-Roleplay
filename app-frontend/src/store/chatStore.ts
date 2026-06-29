import { defineStore } from "pinia";
import { ref, computed, watch } from "vue";
import { getSessionHistory, updateMessage as apiUpdateMessage, deleteMessage as apiDeleteMessage, switchCandidate as apiSwitchCandidate } from "@/api/sessions";
import type { Message } from "@/api/sessions";
import { sendMessageStream } from "@/api/chat";
import type { ChatResponse, ChatRequest } from "@/api/chat";
import { getBaseUrl, getSavedApiKey } from "@/api/config";
import { usePersonaStore } from "./personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { useChatSettingsStore } from "./chatSettingsStore";

export type MessageStatus = "sending" | "streaming" | "done" | "error";

export interface ChatMessage extends Message {
  status?: MessageStatus;
  tempId?: string; // Optimistic update ID before server confirms
  clientId?: string; // Stable client-side unique ID for DOM rendering
}

export const useChatStore = defineStore("chat", () => {
  // ===== 状态变量 =====

  /** 当前活跃的会话 ID */
  const activeSessionId = ref<number | null>(null);

  /** 当前会话的所有消息列表 */
  const messages = ref<ChatMessage[]>([]);

  /** 当前是否有正在发送的对话请求 */
  const isLoading = ref(false);

  /** 当前流式输出传输中的临时回复文本 */
  const streamingText = ref("");

  /** 从服务端接收到的最新对话元数据 */
  const lastMeta = ref<Omit<ChatResponse, "reply"> | null>(null);

  /** 若上一次请求失败，所记录的错误提示信息 */
  const errorMessage = ref<string | null>(null);

  /** 当前活跃的 App 端流式请求（用于 renderjs 通信） */
  const activeStreamRequest = ref<{
    requestId: string;
    placeholderId: string;
    userMessageTempId?: string;
    params: ChatRequest;
    baseUrl: string;
    apiKey: string;
    timestamp: number;
  } | null>(null);



  // ===== 计算属性 (Getters) =====

  const hasMessages = computed(() => messages.value.length > 0);

  const isStreaming = computed(() =>
    messages.value.some((m) => m.status === "streaming")
  );

  const lastAssistantMessage = computed(() =>
    [...messages.value].reverse().find((m) => m.role === "assistant")
  );

  // ===== 操作方法 (Actions) =====

  /** 设置当前活跃会话并从后端加载其历史记录 */
  async function loadHistory(sessionId: number) {
    activeSessionId.value = sessionId;
    messages.value = [];
    errorMessage.value = null;
    lastMeta.value = null;
    isLoading.value = true;
    activeStreamRequest.value = null;
    
    // 加载会话历史时重置当前自定义参数，以保证使用后端新会话的默认值
    const settingsStore = useChatSettingsStore();
    settingsStore.clearParameters();

    try {
      const res = await getSessionHistory(sessionId);
      setHistory(res.messages);
    } catch (e: any) {
      setError(e.message || "Failed to load chat history");
    } finally {
      isLoading.value = false;
    }
  }

  /** 手动设置活跃会话并清空已有的历史消息记录 */
  function setActiveSession(sessionId: number) {
    activeSessionId.value = sessionId;
    messages.value = [];
    errorMessage.value = null;
    lastMeta.value = null;
  }

  /** 将历史消息记录加载至本地 store 中 */
  function setHistory(history: Message[]) {
    messages.value = history.map((m) => ({
      ...m,
      status: "done",
      clientId: `msg-${m.id}`
    }));
  }

  /** 在消息列表末尾追加一条新消息 */
  function appendMessage(message: ChatMessage) {
    if (!message.clientId) {
      message.clientId = message.id ? `msg-${message.id}` : `msg-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    }
    messages.value.push(message);
  }

  /** 在后端修改单条消息的内容并更新本地 store 缓存 */
  async function editMessage(id: number, content: string) {
    try {
      await apiUpdateMessage(id, content);
      const idx = messages.value.findIndex((m) => m.id === id);
      if (idx !== -1) {
        messages.value[idx].content = content;
      }
    } catch (e: any) {
      console.error("Failed to update message", e);
    }
  }

  /** 在后端删除单条消息并同步从本地移除 */
  async function deleteMessageById(id: number) {
    try {
      const res = await apiDeleteMessage(id);
      
      // 1. 查找此消息在本地列表中对应的气泡对象
      const idx = messages.value.findIndex((m) => m.id === id);
      if (idx !== -1) {
        const msg = messages.value[idx];
        
        // 2. 如果是 assistant 消息，且存在其他候选回复
        if (msg.role === "assistant" && msg.candidates && msg.candidates.length > 1) {
          // 过滤掉当前被删的候选
          msg.candidates = msg.candidates.filter((c) => c.id !== id);
          
          // 选择 ID 最大的剩下的候选作为替补（与后端 sibling = id.desc().first() 规则保持一致）
          const sortedCandidates = [...msg.candidates].sort((a, b) => b.id - a.id);
          const sibling = sortedCandidates[0];
          
          if (sibling) {
            // 更新当前气泡的数据为新的替补候选
            msg.id = sibling.id;
            msg.content = sibling.content;
            msg.emotion_tag = sibling.emotion_tag;
            msg.affection_change = sibling.affection_change;
            msg.audio_path = sibling.audio_path || null;
            msg.clientId = `msg-${sibling.id}`; // 保持 clientId 一致
            
            // 重新计算活动 index
            const activeIdx = msg.candidates.findIndex((c) => c.id === sibling.id);
            msg.active_index = activeIdx !== -1 ? activeIdx : 0;
            
            // 更新 Persona 的好感度
            const personaStore = usePersonaStore();
            if (res.affection_score !== null && res.affection_score !== undefined) {
              personaStore.applyAffectionChange(
                0,
                res.affection_score,
                res.current_mood || undefined
              );
            }
            return;
          }
        }
      }
      
      // 3. 常规删除：如果没有候选替补，或者该消息不是 assistant 消息，则直接移除整个气泡
      messages.value = messages.value.filter((m) => m.id !== id);
      
      // 同时应用好感度与心情变更到 Persona Store
      const personaStore = usePersonaStore();
      if (res.affection_score !== null && res.affection_score !== undefined) {
        personaStore.applyAffectionChange(
          0,
          res.affection_score,
          res.current_mood || undefined
        );
      }
    } catch (e: any) {
      console.error("Failed to delete message", e);
    }
  }

  /** 重新生成最后一次 AI 回复（支持无感重发，避免出现双重用户气泡的 Bug） */
  async function regenerateChatMessage(sessionId: number) {
    if (isLoading.value) return;
    
    const personaStore = usePersonaStore();
    
    // 1. 查找最后一条属于用户的历史消息以提取其内容
    const lastUserMsg = [...messages.value].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;

    isLoading.value = true;
    clearError();

    // 2. 如果当前最后一条消息是 AI 的回复，直接从本地消息缓存中移出
    //（后端在 /chat 接口收到 is_regenerate: true 时会自动物理删除最新的 AI 消息，这里无需调用 apiDeleteMessage，防止发生“双重删除”导致上一条回复也被删掉的 Bug）
    const lastMsg = messages.value[messages.value.length - 1];
    if (lastMsg && lastMsg.role === "assistant") {
      messages.value.pop();
    }

    // 3. 直接建立流式占位符开启第二轮 AI 生成，无需二次追加用户消息副本
    const streamPlaceholderId = addStreamingPlaceholder();

    const settingsStore = useChatSettingsStore();
    const requestParams: ChatRequest = { 
      session_id: sessionId, 
      user_message: lastUserMsg.content,
      use_reasoning: settingsStore.useReasoning,
      is_regenerate: true,
      user_nickname: personaStore.userNickname,
      temperature: settingsStore.temperature ?? undefined,
      top_p: settingsStore.top_p ?? undefined,
      presence_penalty: settingsStore.presence_penalty ?? undefined,
      frequency_penalty: settingsStore.frequency_penalty ?? undefined,
      repetition_penalty: settingsStore.repetition_penalty ?? undefined,
    };

    // #ifdef APP-PLUS
    const requestId = `req-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    activeStreamRequest.value = {
      requestId,
      placeholderId: streamPlaceholderId,
      params: requestParams,
      baseUrl: getBaseUrl(),
      apiKey: getSavedApiKey(),
      timestamp: Date.now()
    };
    // #endif

    // #ifndef APP-PLUS
    try {
      await sendMessageStream(
        requestParams,
        (chunk) => {
          appendStreamChunk(streamPlaceholderId, chunk);
        },
        (meta) => {
          const finalId = (meta as any).assistant_message_id || Date.now();
          const candidates = (meta as any).candidates || [];
          const activeIndex = (meta as any).active_index ?? (candidates.length - 1);
          const finalReasoning = candidates[activeIndex]?.reasoning_content || "";
          
          finalizeStream(streamPlaceholderId, {
            id: finalId,
            role: "assistant",
            emotion_tag: meta.emotion_tag,
            affection_change: meta.affection_change,
            created_at: new Date().toISOString(),
            model_used: (meta as any).model_used,
            parent_id: (meta as any).user_message_id,
            is_active: true,
            candidates: (meta as any).candidates,
            active_index: (meta as any).active_index,
            reasoning_content: finalReasoning || undefined,
          });
          
          // 同步好感度分数与当前情绪到 Pinia Persona Store 状态库
          personaStore.applyAffectionChange(
            meta.affection_change,
            meta.affection_score,
            meta.emotion_tag
          );
          
          isLoading.value = false;
        },
        (err) => {
          // 发生异常时回滚占位消息并设置错误状态
          messages.value = messages.value.filter((m) => m.tempId !== streamPlaceholderId);
          setError(err.message || "Failed to regenerate AI response");
          isLoading.value = false;
        },
        (rChunk) => {
          appendStreamReasoningChunk(streamPlaceholderId, rChunk);
        }
      );
    } catch (e: any) {
      setError(e.message || "An unexpected error occurred");
      isLoading.value = false;
    }
    // #endif
  }

  /** 发送一条新消息并处理流式返回的分块数据 */
  async function sendChatMessage(sessionId: number, text: string) {
    if (isLoading.value) return;
    
    const personaStore = usePersonaStore();
    
    isLoading.value = true;
    clearError();

    const tempId = addOptimisticUserMessage(text);
    const streamPlaceholderId = addStreamingPlaceholder();

    const settingsStore = useChatSettingsStore();
    const requestParams: ChatRequest = { 
      session_id: sessionId, 
      user_message: text,
      use_reasoning: settingsStore.useReasoning,
      user_nickname: personaStore.userNickname,
      temperature: settingsStore.temperature ?? undefined,
      top_p: settingsStore.top_p ?? undefined,
      presence_penalty: settingsStore.presence_penalty ?? undefined,
      frequency_penalty: settingsStore.frequency_penalty ?? undefined,
      repetition_penalty: settingsStore.repetition_penalty ?? undefined,
    };

    // #ifdef APP-PLUS
    const requestId = `req-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    activeStreamRequest.value = {
      requestId,
      placeholderId: streamPlaceholderId,
      userMessageTempId: tempId,
      params: requestParams,
      baseUrl: getBaseUrl(),
      apiKey: getSavedApiKey(),
      timestamp: Date.now()
    };
    // #endif

    // #ifndef APP-PLUS
    try {
      await sendMessageStream(
        requestParams,
        (chunk) => {
          appendStreamChunk(streamPlaceholderId, chunk);
        },
        (meta) => {
          const finalId = (meta as any).assistant_message_id || Date.now();
          const candidates = (meta as any).candidates || [];
          const activeIndex = (meta as any).active_index ?? (candidates.length - 1);
          const finalReasoning = candidates[activeIndex]?.reasoning_content || "";

          finalizeStream(streamPlaceholderId, {
            id: finalId,
            role: "assistant",
            emotion_tag: meta.emotion_tag,
            affection_change: meta.affection_change,
            created_at: new Date().toISOString(),
            model_used: (meta as any).model_used,
            parent_id: (meta as any).user_message_id,
            is_active: true,
            candidates: (meta as any).candidates,
            active_index: (meta as any).active_index,
            reasoning_content: finalReasoning || undefined,
          });
          
          // 用服务器确认的数据替换用户消息的临时 ID/tempId 并归档
          const userIdx = messages.value.findIndex((m) => m.tempId === tempId);
          if (userIdx !== -1) {
            messages.value[userIdx].status = "done";
            if ((meta as any).user_message_id) {
              messages.value[userIdx].id = (meta as any).user_message_id;
            }
          }

          // 同步好感度分数与当前情绪到 Pinia Persona Store 状态库
          personaStore.applyAffectionChange(
            meta.affection_change,
            meta.affection_score,
            meta.emotion_tag
          );
          
          isLoading.value = false;
        },
        (err) => {
          // 发生异常时回滚占位消息并设置错误状态
          messages.value = messages.value.filter((m) => m.tempId !== streamPlaceholderId);
          const userIdx = messages.value.findIndex((m) => m.tempId === tempId);
          if (userIdx !== -1) {
            messages.value[userIdx].status = "error";
          }
          setError(err.message || "Failed to get AI response");
          isLoading.value = false;
        },
        (rChunk) => {
          appendStreamReasoningChunk(streamPlaceholderId, rChunk);
        }
      );
    } catch (e: any) {
      setError(e.message || "An unexpected error occurred");
      isLoading.value = false;
    }
    // #endif
  }

  /** 乐观更新：在服务器确认前立即向列表添加用户发送的消息 */
  function addOptimisticUserMessage(content: string): string {
    const tempId = `temp-${Date.now()}`;
    const clientId = `user-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    messages.value.push({
      id: -Date.now(), // 使用负数 ID 与服务器返回的真实正数 ID 做区分
      clientId,
      role: "user",
      content,
      emotion_tag: null,
      affection_change: null,
      created_at: new Date().toISOString(),
      status: "sending",
      tempId,
    });
    return tempId;
  }

  /** 乐观更新：向列表追加一条流式传输专用的 AI 占位消息 */
  function addStreamingPlaceholder(): string {
    const tempId = `stream-${Date.now()}`;
    const clientId = `assistant-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    messages.value.push({
      id: -Date.now() - 1,
      clientId,
      role: "assistant",
      content: "",
      reasoning_content: "",
      emotion_tag: null,
      affection_change: null,
      created_at: new Date().toISOString(),
      status: "streaming",
      tempId,
    });
    streamingText.value = "";
    return tempId;
  }

  /** 向流式传输中的占位消息追加文本分块 */
  function appendStreamChunk(tempId: string, chunk: string) {
    const msg = messages.value.find((m) => m.tempId === tempId);
    if (msg) {
      msg.content += chunk;
      streamingText.value += chunk;
    }
  }

  /** 向流式传输中的占位消息追加思考过程文本分块 */
  function appendStreamReasoningChunk(tempId: string, chunk: string) {
    const msg = messages.value.find((m) => m.tempId === tempId);
    if (msg) {
      if (msg.reasoning_content === undefined || msg.reasoning_content === null) {
        msg.reasoning_content = "";
      }
      msg.reasoning_content += chunk;
    }
  }

  /** 使用服务器最终确认的数据归档流式传输消息 */
  function finalizeStream(
    tempId: string,
    serverMessage: Partial<ChatMessage>
  ) {
    const idx = messages.value.findIndex((m) => m.tempId === tempId);
    if (idx !== -1) {
      messages.value[idx] = {
        ...messages.value[idx],
        ...serverMessage,
        status: "done",
        tempId: undefined,
      };
    }
    streamingText.value = "";
  }

  /** 设置错误状态信息 */
  function setError(msg: string) {
    errorMessage.value = msg;
    isLoading.value = false;
  }

  /** 清除当前的错误状态 */
  function clearError() {
    errorMessage.value = null;
  }

  async function switchActiveCandidate(messageId: number, targetCandidateId: number) {
    const { stopMessageTTS } = useAudioPlayer();
    stopMessageTTS(); // 切换候选版本时立刻停止当前播放的音频，避免音画不同步
    errorMessage.value = null;
    try {
      const res = await apiSwitchCandidate(targetCandidateId);
      
      const msgIdx = messages.value.findIndex((m) => m.id === messageId);
      if (msgIdx !== -1) {
        const targetMsg = messages.value[msgIdx];
        const candidate = targetMsg.candidates?.find((c) => c.id === targetCandidateId);
        if (candidate) {
          targetMsg.id = candidate.id;
          targetMsg.content = candidate.content;
          targetMsg.emotion_tag = candidate.emotion_tag;
          targetMsg.affection_change = candidate.affection_change;
          targetMsg.created_at = candidate.created_at;
          targetMsg.audio_path = (candidate as any).audio_path || null;
          
          const activeIdx = targetMsg.candidates?.findIndex((c) => c.id === targetCandidateId) ?? 0;
          targetMsg.active_index = activeIdx;
        }
      }
      
      const personaStore = usePersonaStore();
      if (res.affection_score !== null) {
        personaStore.applyAffectionChange(
          0,
          res.affection_score,
          res.current_mood || undefined
        );
      }
    } catch (e: any) {
      setError(e.message || "Failed to switch reply version");
    }
  }

  async function loadMoreHistory() {
    if (isLoading.value || activeSessionId.value === null) return false;
    if (messages.value.length === 0) return false;
    
    const validMessages = messages.value.filter((m) => m.id > 0);
    if (validMessages.length === 0) return false;
    
    const oldestMsgId = validMessages[0].id;
    isLoading.value = true;
    
    try {
      const res = await getSessionHistory(activeSessionId.value, 50, oldestMsgId);
      if (res.messages && res.messages.length > 0) {
        const newMsgs = res.messages.map((m) => ({
          ...m,
          status: "done" as const,
          clientId: `msg-${m.id}`
        }));
        messages.value = [...newMsgs, ...messages.value];
        isLoading.value = false;
        return true;
      }
    } catch (e: any) {
      console.error("Failed to load more chat history", e);
    } finally {
      isLoading.value = false;
    }
    return false;
  }

  /** 重置整个 Store 的状态变量 */
  function $reset() {
    const { stopMessageTTS } = useAudioPlayer();
    stopMessageTTS();
    activeSessionId.value = null;
    messages.value = [];
    isLoading.value = false;
    streamingText.value = "";
    lastMeta.value = null;
    errorMessage.value = null;

    const settingsStore = useChatSettingsStore();
    settingsStore.$reset();

    activeStreamRequest.value = null;
  }

  return {
    // State
    activeSessionId,
    messages,
    isLoading,
    streamingText,
    lastMeta,
    errorMessage,
    activeStreamRequest,
    // Getters
    hasMessages,
    isStreaming,
    lastAssistantMessage,
    // Actions
    loadHistory,
    setActiveSession,
    setHistory,
    appendMessage,
    editMessage,
    deleteMessageById,
    regenerateChatMessage,
    sendChatMessage,
    addOptimisticUserMessage,
    addStreamingPlaceholder,
    appendStreamChunk,
    appendStreamReasoningChunk,
    finalizeStream,
    switchActiveCandidate,
    loadMoreHistory,
    setError,
    clearError,
    $reset,
  };
});
