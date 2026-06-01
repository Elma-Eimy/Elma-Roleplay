import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { getSessionHistory, updateMessage as apiUpdateMessage, deleteMessage as apiDeleteMessage } from "@/api/sessions";
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

  /** 若上一次请求失败，所记录的错误提示信息 */
  const errorMessage = ref<string | null>(null);

  /** 是否对聊天回复启用深度思考推理模型 */
  const useReasoning = ref(false);

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
          user_nickname: personaStore.userNickname
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
          user_nickname: personaStore.userNickname
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
            // Optional model_used metadata
            model_used: (meta as any).model_used,
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

  /** 重置整个 Store 的状态变量 */
  function $reset() {
    activeSessionId.value = null;
    messages.value = [];
    isLoading.value = false;
    streamingText.value = "";
    lastMeta.value = null;
    errorMessage.value = null;
    useReasoning.value = false;
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
    setError,
    clearError,
    $reset,
  };
});
