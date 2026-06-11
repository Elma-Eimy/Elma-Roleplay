import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { getSessionHistory, updateMessage as apiUpdateMessage, deleteMessage as apiDeleteMessage, switchCandidate as apiSwitchCandidate } from "@/api/sessions";
import type { Message } from "@/api/sessions";
import { sendMessageStream } from "@/api/chat";
import type { ChatResponse } from "@/api/chat";
import { usePersonaStore } from "./personaStore";

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

  /** 当前正在播放语音的消息 ID */
  const activeAudioMessageId = ref<number | null>(null);

  /** 若上一次请求失败，所记录的错误提示信息 */
  const errorMessage = ref<string | null>(null);

  /** 是否对聊天回复启用深度思考推理模型 */
  const useReasoning = ref(false);

  /** 自定义采样参数值 */
  const temperature = ref<number | null>(null);
  const top_p = ref<number | null>(null);
  const presence_penalty = ref<number | null>(null);
  const frequency_penalty = ref<number | null>(null);
  const repetition_penalty = ref<number | null>(null);

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
    
    // 加载会话历史时重置当前自定义参数，以保证使用后端新会话的默认值
    temperature.value = null;
    top_p.value = null;
    presence_penalty.value = null;
    frequency_penalty.value = null;
    repetition_penalty.value = null;

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
      await apiDeleteMessage(id);
      messages.value = messages.value.filter((m) => m.id !== id);
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

    try {
      await sendMessageStream(
        { 
          session_id: sessionId, 
          user_message: lastUserMsg.content,
          use_reasoning: useReasoning.value,
          is_regenerate: true,
          user_nickname: personaStore.userNickname,
          temperature: temperature.value ?? undefined,
          top_p: top_p.value ?? undefined,
          presence_penalty: presence_penalty.value ?? undefined,
          frequency_penalty: frequency_penalty.value ?? undefined,
          repetition_penalty: repetition_penalty.value ?? undefined,
        },
        (chunk) => {
          appendStreamChunk(streamPlaceholderId, chunk);
        },
        (meta) => {
          const finalId = (meta as any).assistant_message_id || Date.now();
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
        }
      );
    } catch (e: any) {
      setError(e.message || "An unexpected error occurred");
    }
  }

  /** 发送一条新消息并处理流式返回的分块数据 */
  async function sendChatMessage(sessionId: number, text: string) {
    if (isLoading.value) return;
    
    const personaStore = usePersonaStore();
    
    isLoading.value = true;
    clearError();

    const tempId = addOptimisticUserMessage(text);
    const streamPlaceholderId = addStreamingPlaceholder();

    try {
      await sendMessageStream(
        { 
          session_id: sessionId, 
          user_message: text,
          use_reasoning: useReasoning.value,
          user_nickname: personaStore.userNickname,
          temperature: temperature.value ?? undefined,
          top_p: top_p.value ?? undefined,
          presence_penalty: presence_penalty.value ?? undefined,
          frequency_penalty: frequency_penalty.value ?? undefined,
          repetition_penalty: repetition_penalty.value ?? undefined,
        },
        (chunk) => {
          appendStreamChunk(streamPlaceholderId, chunk);
        },
        (meta) => {
          const finalId = (meta as any).assistant_message_id || Date.now();
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
        }
      );
    } catch (e: any) {
      setError(e.message || "An unexpected error occurred");
    }
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

  let innerAudioContext: any = null;

  function initAudioContext() {
    if (!innerAudioContext) {
      // #ifdef APP-PLUS || H5 || MP-WEIXIN
      innerAudioContext = uni.createInnerAudioContext();
      // #endif
      if (innerAudioContext) {
        innerAudioContext.onPlay(() => {
          console.log("Audio playing...");
        });
        innerAudioContext.onEnded(() => {
          console.log("Audio finished.");
          activeAudioMessageId.value = null;
        });
        innerAudioContext.onError((err: any) => {
          console.error("Audio error:", err);
          activeAudioMessageId.value = null;
          uni.showToast({ title: "语音播放失败", icon: "none" });
        });
        innerAudioContext.onStop(() => {
          console.log("Audio stopped.");
          activeAudioMessageId.value = null;
        });
      }
    }
  }

  async function playMessageTTS(messageId: number, content: string) {
    initAudioContext();
    if (!innerAudioContext) {
      uni.showToast({ title: "您的平台不支持音频播放", icon: "none" });
      return;
    }

    // 如果当前正在播放的就是这条消息，点击则是停止播放
    if (activeAudioMessageId.value === messageId) {
      innerAudioContext.stop();
      activeAudioMessageId.value = null;
      return;
    }

    // 如果正在播放其他消息，先停止
    if (activeAudioMessageId.value !== null) {
      innerAudioContext.stop();
    }

    const msgIdx = messages.value.findIndex((m) => m.id === messageId);
    if (msgIdx === -1) return;

    const msg = messages.value[msgIdx];
    let audioUrl = msg.audio_path;

    if (!audioUrl) {
      uni.showLoading({ title: "正在合成语音..." });
      try {
        const { generateTTS } = await import("@/api/chat");
        const res = await generateTTS(messageId, content);
        audioUrl = res.audio_url;
        msg.audio_path = audioUrl;
        uni.hideLoading();
      } catch (e: any) {
        uni.hideLoading();
        uni.showToast({ title: e.message || "语音合成失败", icon: "none" });
        return;
      }
    }

    if (audioUrl) {
      const { getBaseUrl, getSavedApiKey } = await import("@/api/config");
      let fullUrl = audioUrl.startsWith("http") ? audioUrl : `${getBaseUrl()}${audioUrl}`;
      
      // 附加 API Key 凭证以支持安全路由参数校验
      const apiKey = getSavedApiKey();
      if (apiKey) {
        fullUrl += `${fullUrl.includes("?") ? "&" : "?"}token=${encodeURIComponent(apiKey)}`;
      }
      
      console.log("Playing audio:", fullUrl);
      activeAudioMessageId.value = messageId;

      // #ifdef APP-PLUS
      // 移动端 App 下载到本地临时文件播放，解决原生 MediaPlayer 播放网络流可能失败或被拦截的问题
      uni.downloadFile({
        url: encodeURI(fullUrl),
        success: (res) => {
          if (res.statusCode === 200) {
            console.log("Audio downloaded successfully:", res.tempFilePath);
            innerAudioContext.src = res.tempFilePath;
            innerAudioContext.play();
          } else {
            console.error("Audio download status error:", res.statusCode);
            uni.showToast({ title: "音频下载失败", icon: "none" });
            activeAudioMessageId.value = null;
          }
        },
        fail: (err) => {
          console.error("Audio download failed:", err);
          uni.showToast({ title: "音频下载失败", icon: "none" });
          activeAudioMessageId.value = null;
        }
      });
      // #endif

      // #ifndef APP-PLUS
      // H5/小程序等平台直接在线播放
      innerAudioContext.src = encodeURI(fullUrl);
      innerAudioContext.play();
      // #endif
    } else {
      uni.showToast({ title: "未获取到有效的语音文件", icon: "none" });
    }
  }

  function stopMessageTTS() {
    if (innerAudioContext && activeAudioMessageId.value !== null) {
      innerAudioContext.stop();
      activeAudioMessageId.value = null;
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
    stopMessageTTS();
    activeSessionId.value = null;
    messages.value = [];
    isLoading.value = false;
    streamingText.value = "";
    lastMeta.value = null;
    errorMessage.value = null;
    useReasoning.value = false;
    temperature.value = null;
    top_p.value = null;
    presence_penalty.value = null;
    frequency_penalty.value = null;
    repetition_penalty.value = null;
    activeAudioMessageId.value = null;
  }

  return {
    // State
    activeSessionId,
    messages,
    isLoading,
    streamingText,
    lastMeta,
    errorMessage,
    useReasoning,
    temperature,
    top_p,
    presence_penalty,
    frequency_penalty,
    repetition_penalty,
    activeAudioMessageId,
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
    finalizeStream,
    switchActiveCandidate,
    playMessageTTS,
    stopMessageTTS,
    loadMoreHistory,
    setError,
    clearError,
    $reset,
  };
});
