import type { ChatRequest } from "@/api/chat";
import type { Message, MessageCandidate } from "@/api/sessions";
import type { ActiveStreamRequest } from "@/types/chatStream";
import type { GenerationOverride } from "@/types/generation";

export interface ChatSamplingParams {
  temperature?: number | null;
  top_p?: number | null;
  presence_penalty?: number | null;
  frequency_penalty?: number | null;
  repetition_penalty?: number | null;
}

export interface ChatRequestMessageLike {
  id: number;
  content: string;
  emotion_tag?: string | null;
  affection_change?: number | null;
  created_at?: string;
  audio_path?: string | null;
  clientId?: string;
  candidates?: MessageCandidate[];
  active_index?: number;
}

/** 从当前消息与候选版本中计算已持久化的最大服务端消息 ID。 */
export function findLatestPersistedMessageId(messages: ReadonlyArray<Pick<Message, "id" | "candidates">>): number {
  return messages.reduce(
    (latest, message) =>
      Math.max(
        latest,
        message.id > 0 ? message.id : 0,
        ...(message.candidates?.map((candidate) => candidate.id) ?? [])
      ),
    0
  );
}

/** 统一装配单聊发送与重新生成请求体。 */
export function buildChatRequest(
  sessionId: number,
  text: string,
  generation: GenerationOverride,
  userNickname: string,
  sampling: ChatSamplingParams,
  isRegenerate = false
): ChatRequest {
  const payload: ChatRequest = {
    session_id: sessionId,
    user_message: text,
    ...generation,
    user_nickname: userNickname,
    temperature: sampling.temperature ?? undefined,
    top_p: sampling.top_p ?? undefined,
    presence_penalty: sampling.presence_penalty ?? undefined,
    frequency_penalty: sampling.frequency_penalty ?? undefined,
    repetition_penalty: sampling.repetition_penalty ?? undefined,
  };
  if (isRegenerate) {
    payload.is_regenerate = true;
  }
  return payload;
}

/** 统一创建 App RenderJS 流传输请求描述。 */
export function createAppStreamRequest(options: {
  placeholderId: string;
  params: ChatRequest;
  baseUrl: string;
  apiKey: string;
  userMessageTempId?: string;
}): ActiveStreamRequest {
  return {
    requestId: `req-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    placeholderId: options.placeholderId,
    ...(options.userMessageTempId ? { userMessageTempId: options.userMessageTempId } : {}),
    params: options.params,
    baseUrl: options.baseUrl,
    apiKey: options.apiKey,
    timestamp: Date.now(),
  };
}

/** 将候选版本数据同步到本地消息快照（用于候选切换和删除后替补回退）。 */
export function applyCandidateSnapshot(
  targetMsg: ChatRequestMessageLike,
  candidate: MessageCandidate,
  options: { syncClientId?: boolean; syncCreatedAt?: boolean } = {}
): void {
  targetMsg.id = candidate.id;
  targetMsg.content = candidate.content;
  targetMsg.emotion_tag = candidate.emotion_tag;
  targetMsg.affection_change = candidate.affection_change;
  targetMsg.audio_path = candidate.audio_path || null;
  if (options.syncCreatedAt) {
    targetMsg.created_at = candidate.created_at;
  }
  if (options.syncClientId) {
    targetMsg.clientId = `msg-${candidate.id}`;
  }
  const activeIdx = targetMsg.candidates?.findIndex((c) => c.id === candidate.id) ?? 0;
  targetMsg.active_index = activeIdx !== -1 ? activeIdx : 0;
}
