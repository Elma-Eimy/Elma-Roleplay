import type { ActiveStreamRequest } from "@/types/chatStream";
import { defineStore } from "pinia";
import { ref, computed, onScopeDispose } from "vue";
import type { MessageActionResult } from "@/types/chat";
import { onServerChange } from "@/utils/connectionEvents";
import { getSessionHistory, updateMessage as apiUpdateMessage, deleteMessage as apiDeleteMessage, switchCandidate as apiSwitchCandidate } from "@/api/sessions";
import type { Message } from "@/api/sessions";
import { sendMessageStream } from "@/api/chat";
import type { ChatResponse, ChatRequest } from "@/api/chat";
import { getBaseUrl, getSavedApiKey } from "@/api/config";
import { usePersonaStore } from "./personaStore";
import { useAudioPlayer } from "@/composables/useAudioPlayer";
import { useChatSettingsStore } from "./chatSettingsStore";
import { createCancellation } from "@/utils/cancellation";
import type { Cancellation } from "@/utils/cancellation";

export type MessageStatus = "sending" | "streaming" | "done" | "error";

export interface ChatMessage extends Message {
  status?: MessageStatus;
  tempId?: string; // Optimistic update ID before server confirms
  clientId?: string; // Stable client-side unique ID for DOM rendering
}


export const useChatStore = defineStore("chat", () => {
  let sessionVersion = 0;
  let streamCancellation: Cancellation | null = null;
  const streamBaselines = new Map<string, number>();
  const recoveringStreams = new Set<string>();

  function invalidateRequests() {
    sessionVersion++;
    streamBaselines.clear();
    recoveringStreams.clear();
    streamCancellation?.cancel();
    streamCancellation = null;
    activeStreamRequest.value = null;
    clearPendingStreamChunks();
    streamingText.value = "";
  }

  function captureContext() {
    const version = sessionVersion;
    const sessionId = activeSessionId.value;
    const endpoint = getBaseUrl();
    return () => version === sessionVersion && sessionId === activeSessionId.value && endpoint === getBaseUrl();
  }
  // ===== 状态变量 =====

  /** 当前活跃的会话 ID */
  const activeSessionId = ref<number | null>(null);

  /** 当前会话的所有消息列表 */
  const messages = ref<ChatMessage[]>([]);

  /** 当前是否有正在发送的对话请求 */
  const isLoading = ref(false);

  /** 当前流式输出传输中的临时回复文本 */
  const streamingText = ref("");

  const STREAM_UPDATE_INTERVAL = 48;
  const pendingStreamText = new Map<string, string>();
  const pendingReasoningText = new Map<string, string>();
  let streamFlushTimer: ReturnType<typeof setTimeout> | null = null;

  const flushPendingStreamChunks = () => {
    if (streamFlushTimer !== null) {
      clearTimeout(streamFlushTimer);
      streamFlushTimer = null;
    }

    pendingStreamText.forEach((text, tempId) => {
      const message = messages.value.find((item) => item.tempId === tempId);
      if (message) {
        message.content += text;
        streamingText.value += text;
      }
    });
    pendingReasoningText.forEach((text, tempId) => {
      const message = messages.value.find((item) => item.tempId === tempId);
      if (message) {
        message.reasoning_content = `${message.reasoning_content || ""}${text}`;
      }
    });

    pendingStreamText.clear();
    pendingReasoningText.clear();
  };

  const scheduleStreamFlush = () => {
    if (streamFlushTimer !== null) return;
    streamFlushTimer = setTimeout(
      flushPendingStreamChunks,
      STREAM_UPDATE_INTERVAL
    );
  };

  const clearPendingStreamChunks = () => {
    if (streamFlushTimer !== null) {
      clearTimeout(streamFlushTimer);
      streamFlushTimer = null;
    }
    pendingStreamText.clear();
    pendingReasoningText.clear();
  };

  /** 从服务端接收到的最新对话元数据 */
  const lastMeta = ref<Omit<ChatResponse, "reply"> | null>(null);

  /** 若上一次请求失败，所记录的错误提示信息 */
  const errorMessage = ref<string | null>(null);

  /** 当前活跃的 App 端流式请求（用于 renderjs 通信） */
  const activeStreamRequest = ref<ActiveStreamRequest | null>(null);



  // ===== 计算属性 (Getters) =====

  const hasMessages = computed(() => messages.value.length > 0);

  const isStreaming = computed(() =>
    messages.value.some((m) => m.status === "streaming")
  );

  const lastAssistantMessage = computed(() =>
    [...messages.value].reverse().find((m) => m.role === "assistant")
  );

  // ===== 操作方法 (Actions) =====

  interface PollPendingOptions {
    placeholderId?: string;
    userMessageTempId?: string;
    fallbackErrorMessage?: string;
    afterMessageId?: number;
  }

  function latestPersistedMessageId() {
    return messages.value.reduce((latest, message) => Math.max(
      latest, message.id > 0 ? message.id : 0,
      ...(message.candidates?.map((candidate) => candidate.id) ?? [])
    ), 0);
  }

  /** 只读历史恢复；服务端仍在生成时持续等待，不重新提交聊天请求。 */
  async function pollPendingGeneration(
    sessionId: number,
    version: number,
    options: PollPendingOptions = {}
  ) {
    const MAX_NETWORK_ERRORS = 15;
    let networkErrors = 0;
    const endpoint = getBaseUrl();
    const current = () => version === sessionVersion && activeSessionId.value === sessionId &&
      endpoint === getBaseUrl() &&
      (!options.placeholderId || messages.value.some((message) =>
        message.tempId === options.placeholderId && message.status === "streaming"));

    while (current()) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      if (!current()) return;
      try {
        const result = await getSessionHistory(sessionId);
        if (!current()) return;
        networkErrors = 0;
        if (result.is_generating) continue;

        const lastMessage = result.messages[result.messages.length - 1];
        const completed = lastMessage?.role === "assistant" &&
          (options.afterMessageId === undefined || lastMessage.id > options.afterMessageId);
        clearPendingStreamChunks();
        streamingText.value = "";
        activeStreamRequest.value = null;
        if (completed) {
          setHistory(result.messages);
          isLoading.value = false;
          errorMessage.value = null;
          if (options.placeholderId) streamBaselines.delete(options.placeholderId);
          void usePersonaStore().loadSessionDetail(sessionId);
        } else if (options.placeholderId) {
          // 本地提交失败时保留用户原话；重新生成失败则恢复原来的候选。
          const failedUserMessage = options.userMessageTempId
            ? messages.value.find((message) => message.tempId === options.userMessageTempId)
            : undefined;
          setHistory(result.messages);
          if (failedUserMessage) appendMessage({ ...failedUserMessage, status: "error" });
          streamBaselines.delete(options.placeholderId);
          setError(options.fallbackErrorMessage || "回复生成失败，请重试");
        } else {
          // 返回会话后以后端历史为准，移除被 abort 删除的用户消息。
          setHistory(result.messages);
          setError("回复生成失败，请重试");
        }
        return;
      } catch (error) {
        if (!current()) return;
        console.warn("[chatStore] Failed to recover generation", error);
        if (++networkErrors < MAX_NETWORK_ERRORS) continue;
        const message = "暂时无法确认回复状态，请恢复网络后重新进入会话查看";
        if (options.placeholderId) {
          failStream(options.placeholderId, message, options.userMessageTempId);
        } else {
          messages.value = messages.value.filter((item) => item.status !== "streaming");
          setError(message);
        }
        return;
      }
    }
  }

  /** H5、小程序和 App 共用断连恢复，使用发送前的消息边界排除旧回复。 */
  async function handleStreamError(
    placeholderId: string,
    error: Error | string,
    userMessageTempId?: string
  ) {
    const sessionId = activeSessionId.value;
    if (sessionId === null || recoveringStreams.has(placeholderId) ||
        !messages.value.some((message) => message.tempId === placeholderId && message.status === "streaming")) return;
    const errorMessage = error instanceof Error ? error.message : String(error);
    if (/\b(?:401|403|404|422)\b/.test(errorMessage)) {
      failStream(placeholderId, errorMessage, userMessageTempId);
      return;
    }
    const version = sessionVersion;
    recoveringStreams.add(placeholderId);
    try {
      await pollPendingGeneration(sessionId, version, {
        placeholderId,
        userMessageTempId,
        fallbackErrorMessage: errorMessage,
        afterMessageId: streamBaselines.get(placeholderId) ?? latestPersistedMessageId(),
      });
    } finally {
      recoveringStreams.delete(placeholderId);
    }
  }

  /** 设置当前活跃会话并从后端加载其历史记录 */
  async function loadHistory(sessionId: number) {
    invalidateRequests();
    const version = sessionVersion;
    activeSessionId.value = sessionId;
    const current = captureContext();
    messages.value = [];
    errorMessage.value = null;
    lastMeta.value = null;
    isLoading.value = true;
    activeStreamRequest.value = null;
    
    // 加载会话历史时重置当前自定义参数，以保证使用后端新会话的默认值
    const settingsStore = useChatSettingsStore();
    settingsStore.clearParameters();
    settingsStore.activateSession(sessionId);

    let isStillGenerating = false;
    try {
      const res = await getSessionHistory(sessionId);
      if (!current()) return;
      setHistory(res.messages);

      if (res.is_generating) {
        isStillGenerating = true;
        const placeholderId = addStreamingPlaceholder();
        void pollPendingGeneration(sessionId, version, { placeholderId });
      }
    } catch (e: any) {
      if (!current()) return;
      setError(e.message || "Failed to load chat history");
    } finally {
      if (current() && !isStillGenerating) isLoading.value = false;
    }
  }

  /** 手动设置活跃会话并清空已有的历史消息记录 */
  function setActiveSession(sessionId: number) {
    useChatSettingsStore().activateSession(sessionId);
    invalidateRequests();
    activeSessionId.value = sessionId;
    messages.value = [];
    errorMessage.value = null;
    lastMeta.value = null;
    isLoading.value = false;
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
  async function editMessage(id: number, content: string): Promise<MessageActionResult> {
    if (activeSessionId.value === null) return { status: "stale" };
    const current = captureContext();
    try {
      await apiUpdateMessage(id, content);
      if (!current()) return { status: "stale" };
      const idx = messages.value.findIndex((m) => m.id === id);
      if (idx !== -1) {
        messages.value[idx].content = content;
      }
      return { status: "success" };
    } catch (e: unknown) {
      if (!current()) return { status: "stale" };
      return { status: "error", message: e instanceof Error ? e.message : "消息保存失败，请重试" };
    }
  }

  /** 在后端删除单条消息并同步从本地移除 */
  async function deleteMessageById(id: number): Promise<MessageActionResult> {
    if (activeSessionId.value === null) return { status: "stale" };
    const current = captureContext();
    try {
      const res = await apiDeleteMessage(id);
      if (!current()) return { status: "stale" };
      
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
            return { status: "success" };
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
      return { status: "success" };
    } catch (e: unknown) {
      if (!current()) return { status: "stale" };
      const message = e instanceof Error ? e.message : "消息删除失败，请重试";
      errorMessage.value = message;
      return { status: "error", message };
    }
  }

  async function receiveCurrentStream(params: ChatRequest, placeholderId: string, userTempId?: string) {
    const contextIsCurrent = captureContext();
    const cancellation = createCancellation();
    streamCancellation = cancellation;
    const current = () => contextIsCurrent() && !cancellation.cancelled;
    try {
      await sendMessageStream(
        params,
        (chunk) => { if (current()) appendStreamChunk(placeholderId, chunk); },
        (meta) => {
          if (!current()) return;
          streamCancellation = null;
          completeStream(placeholderId, meta, userTempId);
        },
        (error) => {
          if (!current()) return;
          streamCancellation = null;
          void handleStreamError(placeholderId, error, userTempId);
        },
        (chunk) => { if (current()) appendStreamReasoningChunk(placeholderId, chunk); },
        cancellation
      );
    } catch (error) {
      if (current()) void handleStreamError(placeholderId, error instanceof Error ? error : String(error), userTempId);
    }
  }

  /** 重新生成最后一次 AI 回复（支持无感重发，避免出现双重用户气泡的 Bug） */
  async function regenerateChatMessage(sessionId: number) {
    if (isLoading.value || activeSessionId.value !== sessionId) return;
    
    const personaStore = usePersonaStore();
    
    // 1. 查找最后一条属于用户的历史消息以提取其内容
    const lastUserMsg = [...messages.value].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;

    isLoading.value = true;
    clearError();
    const version = sessionVersion;
    const endpoint = getBaseUrl();
    let generation;
    try {
      generation = await useChatSettingsStore().requestGeneration(sessionId);
    } catch (error) {
      if (version === sessionVersion && endpoint === getBaseUrl()) {
        setError(error instanceof Error ? error.message : String(error));
        isLoading.value = false;
      }
      return;
    }
    if (version !== sessionVersion || endpoint !== getBaseUrl() || activeSessionId.value !== sessionId) return;

    const afterMessageId = latestPersistedMessageId();

    // 2. 如果当前最后一条消息是 AI 的回复，直接从本地消息缓存中移出
    //（后端在 /chat 接口收到 is_regenerate: true 时会自动物理删除最新的 AI 消息，这里无需调用 apiDeleteMessage，防止发生“双重删除”导致上一条回复也被删掉的 Bug）
    const lastMsg = messages.value[messages.value.length - 1];
    if (lastMsg && lastMsg.role === "assistant") {
      messages.value.pop();
    }

    // 3. 直接建立流式占位符开启第二轮 AI 生成，无需二次追加用户消息副本
    const streamPlaceholderId = addStreamingPlaceholder();
    streamBaselines.set(streamPlaceholderId, afterMessageId);

    const settingsStore = useChatSettingsStore();
    const requestParams: ChatRequest = { 
      session_id: sessionId, 
      user_message: lastUserMsg.content,
      ...generation,
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
    await receiveCurrentStream(requestParams, streamPlaceholderId);
    // #endif
  }

  /** 发送一条新消息并处理流式返回的分块数据 */
  async function sendChatMessage(sessionId: number, text: string) {
    if (isLoading.value || activeSessionId.value !== sessionId) return;
    
    const personaStore = usePersonaStore();
    
    isLoading.value = true;
    clearError();
    const version = sessionVersion;
    const endpoint = getBaseUrl();
    let generation;
    try {
      generation = await useChatSettingsStore().requestGeneration(sessionId);
    } catch (error) {
      if (version === sessionVersion && endpoint === getBaseUrl()) {
        setError(error instanceof Error ? error.message : String(error));
        isLoading.value = false;
      }
      return;
    }
    if (version !== sessionVersion || endpoint !== getBaseUrl() || activeSessionId.value !== sessionId) return;

    const tempId = addOptimisticUserMessage(text);
    const streamPlaceholderId = addStreamingPlaceholder();

    const settingsStore = useChatSettingsStore();
    const requestParams: ChatRequest = { 
      session_id: sessionId, 
      user_message: text,
      ...generation,
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
    await receiveCurrentStream(requestParams, streamPlaceholderId, tempId);
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
    clearPendingStreamChunks();
    const afterMessageId = latestPersistedMessageId();
    const tempId = `stream-${Date.now()}`;
    streamBaselines.set(tempId, afterMessageId);
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
    if (!messages.value.some((item) => item.tempId === tempId && item.status === "streaming")) return;
    if (!chunk) return;
    pendingStreamText.set(
      tempId,
      `${pendingStreamText.get(tempId) || ""}${chunk}`
    );
    scheduleStreamFlush();
  }

  /** 向流式传输中的占位消息追加思考过程文本分块 */
  function appendStreamReasoningChunk(tempId: string, chunk: string) {
    if (!messages.value.some((item) => item.tempId === tempId && item.status === "streaming")) return;
    if (!chunk) return;
    pendingReasoningText.set(
      tempId,
      `${pendingReasoningText.get(tempId) || ""}${chunk}`
    );
    scheduleStreamFlush();
  }

  /** 使用服务器最终确认的数据归档流式传输消息 */
  function finalizeStream(
    tempId: string,
    serverMessage: Partial<ChatMessage>
  ) {
    flushPendingStreamChunks();
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

  /** 统一处理 H5/小程序流和 App RenderJS 流的成功收尾。 */
  function completeStream(
    tempId: string,
    meta: Partial<Omit<ChatResponse, "reply">>,
    userMessageTempId?: string
  ) {
    if (!messages.value.some((item) => item.tempId === tempId && item.status === "streaming")) return;
    streamBaselines.delete(tempId);
    const candidates = meta.candidates ?? [];
    const activeIndex = meta.active_index ?? candidates.length - 1;
    const activeCandidate = candidates[activeIndex];

    finalizeStream(tempId, {
      id: meta.assistant_message_id ?? Date.now(),
      role: "assistant",
      ...(activeCandidate?.content
        ? { content: activeCandidate.content }
        : {}),
      emotion_tag: meta.emotion_tag ?? null,
      affection_change: meta.affection_change ?? null,
      created_at: new Date().toISOString(),
      model_used: meta.model_used,
      parent_id: meta.user_message_id,
      is_active: true,
      candidates: meta.candidates,
      active_index: meta.active_index,
      reasoning_content: activeCandidate?.reasoning_content ?? undefined,
    });

    if (userMessageTempId) {
      const userMessage = messages.value.find(
        (message) => message.tempId === userMessageTempId
      );
      if (userMessage) {
        userMessage.status = "done";
        if (meta.user_message_id) {
          userMessage.id = meta.user_message_id;
        }
      }
    }

    if (meta.affection_score !== undefined) {
      const personaStore = usePersonaStore();
      personaStore.applyAffectionChange(
        meta.affection_change ?? 0,
        meta.affection_score,
        meta.emotion_tag ?? undefined
      );
    }

    isLoading.value = false;
    activeStreamRequest.value = null;
  }

  /** 统一回滚流式占位消息并标记对应的乐观用户消息。 */
  function failStream(
    tempId: string,
    message: string,
    userMessageTempId?: string
  ) {
    if (!messages.value.some((item) => item.tempId === tempId && item.status === "streaming")) return;
    streamBaselines.delete(tempId);
    messages.value = messages.value.filter((item) => item.tempId !== tempId);
    if (userMessageTempId) {
      const userMessage = messages.value.find(
        (item) => item.tempId === userMessageTempId
      );
      if (userMessage) {
        userMessage.status = "error";
      }
    }
    setError(message);
    activeStreamRequest.value = null;
  }

  /** 设置错误状态信息 */
  function setError(msg: string) {
    clearPendingStreamChunks();
    errorMessage.value = msg;
    isLoading.value = false;
  }

  /** 清除当前的错误状态 */
  function clearError() {
    errorMessage.value = null;
  }

  async function switchActiveCandidate(messageId: number, targetCandidateId: number): Promise<MessageActionResult> {
    if (activeSessionId.value === null) return { status: "stale" };
    const current = captureContext();
    const { stopMessageTTS } = useAudioPlayer();
    stopMessageTTS(); // 切换候选版本时立刻停止当前播放的音频，避免音画不同步
    errorMessage.value = null;
    try {
      const res = await apiSwitchCandidate(targetCandidateId);
      if (!current()) return { status: "stale" };
      
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
          targetMsg.audio_path = candidate.audio_path || null;
          
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
      return { status: "success" };
    } catch (e: unknown) {
      if (!current()) return { status: "stale" };
      const message = e instanceof Error ? e.message : "候选切换失败，请重试";
      errorMessage.value = message;
      return { status: "error", message };
    }
  }

  async function loadMoreHistory() {
    if (isLoading.value || activeSessionId.value === null) return false;
    if (messages.value.length === 0) return false;
    
    const validMessages = messages.value.filter((m) => m.id > 0);
    if (validMessages.length === 0) return false;
    
    const oldestMsgId = validMessages[0].id;
    const sessionId = activeSessionId.value;
    const current = captureContext();
    isLoading.value = true;
    
    try {
      const res = await getSessionHistory(sessionId, 50, oldestMsgId);
      if (!current()) return false;
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
      if (current()) isLoading.value = false;
    }
    return false;
  }

  /** 重置整个 Store 的状态变量 */
  function $reset() {
    invalidateRequests();
    clearPendingStreamChunks();
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

  onScopeDispose(onServerChange($reset));

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
    completeStream,
    failStream,
    handleStreamError,
    switchActiveCandidate,
    loadMoreHistory,
    setError,
    clearError,
    $reset,
  };
});
