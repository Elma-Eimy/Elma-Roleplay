import { receiveChatStream } from "./chatStream";
import { createCancellation } from "../utils/cancellation";
import type { Cancellation } from "../utils/cancellation";
import { request, getBaseUrl, USE_MOCK, getMockDB, setMockDB, getHeaders } from "./config";
import type { MessageCandidate } from "./sessions";

// ===================== 类型定义 =====================

export interface ChatRequest {
  session_id: number;
  user_message: string;
  use_reasoning?: boolean;
  is_regenerate?: boolean;
  user_nickname?: string;
  temperature?: number;
  top_p?: number;
  presence_penalty?: number;
  frequency_penalty?: number;
  repetition_penalty?: number;
}

export interface ChatResponse {
  reply: string;
  emotion_tag: string;
  affection_change: number;
  affection_score: number;
  model_used?: string;
  user_message_id?: number;
  assistant_message_id?: number;
  candidates?: MessageCandidate[];
  active_index?: number;
}

// ===================== API 接口函数 =====================

/**
 * 提交用户消息并接收 AI 角色的回复。
 * POST /chat
 *
 * @param params - session_id 和 user_message
 * @returns 包含 reply、emotion_tag、好感度变化/总分的 ChatResponse
 */
export async function sendMessage(params: ChatRequest): Promise<ChatResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    if (!params.is_regenerate) {
      const userMsg = {
        id: Date.now(),
        role: "user" as const,
        content: params.user_message,
        emotion_tag: null,
        affection_change: null,
        created_at: new Date().toISOString(),
      };
      
      if (!db.messages[params.session_id]) {
        db.messages[params.session_id] = [];
      }
      db.messages[params.session_id].push(userMsg);
    }

    const session = db.sessions.find((s) => s.id === params.session_id);
    const char = db.characters.find((c) => c.id === (session ? session.character_id : 1));
    const characterName = char ? char.name : "AI";

    const reply = `I received your message: "${params.user_message}". This is a mock response from ${characterName}.`;
    const emotion_tag = "Calm";
    const affection_change = 1;

    if (session) {
      session.persona.affection_score = Math.min(100, Math.max(0, session.persona.affection_score + affection_change));
      session.persona.current_mood = emotion_tag;
      session.updated_at = new Date().toISOString();
    }

    const aiMsg = {
      id: Date.now() + 1,
      role: "assistant" as const,
      content: reply,
      emotion_tag,
      affection_change,
      created_at: new Date().toISOString(),
    };
    db.messages[params.session_id].push(aiMsg);
    
    setMockDB(db);

    return {
      reply,
      emotion_tag,
      affection_change,
      affection_score: session ? session.persona.affection_score : 11,
    };
  }

  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ===================== SSE 流式传输 =====================

/**
 * 读取 /chat/stream；H5 使用 fetch，小程序使用 uni.request。
 *
 * @param params - session_id 和 user_message
 * @param onChunk - 接收到每个流式文本分块时的回调函数
 * @param onDone - 流式传输结束并带有最终元数据时的回调函数
 * @param onError - 发生错误时的回调函数
 */
export async function sendMessageStream(
  params: ChatRequest,
  onChunk: (text: string) => void,
  onDone: (meta: Omit<ChatResponse, "reply">) => void,
  onError: (err: Error) => void,
  onReasoningChunk?: (text: string) => void,
  cancellation: Cancellation = createCancellation()
): Promise<void> {
  if (cancellation.cancelled) return;
  if (USE_MOCK) {
    try {
      const db = getMockDB();
      if (!params.is_regenerate) {
        const userMsg = {
          id: Date.now(),
          role: "user" as const,
          content: params.user_message,
          emotion_tag: null,
          affection_change: null,
          created_at: new Date().toISOString(),
        };
        
        if (!db.messages[params.session_id]) {
          db.messages[params.session_id] = [];
        }
        db.messages[params.session_id].push(userMsg);
      }

      const session = db.sessions.find((s) => s.id === params.session_id);
      const char = db.characters.find((c) => c.id === (session ? session.character_id : 1));
      const characterName = char ? char.name : "AI";

      // 动态选择回复内容以模拟多样性
      let responseText = "";
      if (params.user_message.toLowerCase().includes("hello") || params.user_message.toLowerCase().includes("hi")) {
        responseText = `Hi there! I'm ${characterName}. *Smiles warmly.* How is your day going?`;
      } else if (params.user_message.toLowerCase().includes("code") || params.user_message.toLowerCase().includes("python")) {
        responseText = `Sure! I can help you with coding. Here is a simple Python example:\n\n\`\`\`python\ndef greet():\n    print("Hello from ${characterName}!")\n\ngreet()\n\`\`\`\nLet me know what you want to build!`;
      } else {
        responseText = `Interesting choice of words. *Nods thoughtfully.* "${params.user_message}" makes me reflect on our conversation. Let's delve deeper into this.`;
      }

      // 使用定时器模拟流式文本输出
      let index = 0;
      const interval = setInterval(() => {
        if (cancellation.cancelled) return;
        if (index < responseText.length) {
          onChunk(responseText[index]);
          index++;
        } else {
          clearInterval(interval);
          unsubscribe();

          const affection_change = 1;
          const emotion_tag = "Happy";
          
          const dbFinal = getMockDB();
          const sessionFinal = dbFinal.sessions.find((s) => s.id === params.session_id);
          
          if (sessionFinal) {
            sessionFinal.persona.affection_score = Math.min(100, Math.max(0, sessionFinal.persona.affection_score + affection_change));
            sessionFinal.persona.current_mood = emotion_tag;
            sessionFinal.updated_at = new Date().toISOString();
          }

          const aiMsg = {
            id: Date.now() + 1,
            role: "assistant" as const,
            content: responseText,
            emotion_tag,
            affection_change,
            created_at: new Date().toISOString(),
          };
          
          if (!dbFinal.messages[params.session_id]) {
            dbFinal.messages[params.session_id] = [];
          }
          dbFinal.messages[params.session_id].push(aiMsg);
          setMockDB(dbFinal);

          const candidates_list = [];
          if (params.is_regenerate) {
            candidates_list.push({
              id: aiMsg.id - 1000,
              content: "这是先前的候选回复 (Mock)...",
              emotion_tag: "Calm",
              affection_change: 0,
              created_at: new Date(Date.now() - 60000).toISOString()
            });
          }
          candidates_list.push({
            id: aiMsg.id,
            content: aiMsg.content,
            emotion_tag: aiMsg.emotion_tag,
            affection_change: aiMsg.affection_change,
            created_at: aiMsg.created_at
          });

          onDone({
            emotion_tag,
            affection_change,
            affection_score: sessionFinal ? sessionFinal.persona.affection_score : 11,
            model_used: params.use_reasoning ? "mock-reasoning-model (Mock)" : "mock-standard-model (Mock)",
            candidates: candidates_list,
            active_index: candidates_list.length - 1,
            user_message_id: Date.now() - 1,
            assistant_message_id: aiMsg.id
          });
        }
      }, 30);
      const unsubscribe = cancellation.onCancel(() => clearInterval(interval));
    } catch (e) {
      onError(e instanceof Error ? e : new Error(String(e)));
    }
    return;
  }

  await receiveChatStream(
    `${getBaseUrl()}/chat/stream`,
    getHeaders({ "Content-Type": "application/json" }),
    params,
    { chunk: onChunk, done: onDone, error: onError, reasoning: onReasoningChunk },
    cancellation
  );
}

/**
 * 封装前端触发文本转语音 (TTS) 的 API。
 * POST /utils/tts
 */
export interface TTSResponse {
  audio_url: string;
}

export async function generateTTS(
  messageId: number,
  text: string,
  voice?: string,
  speed?: number
): Promise<TTSResponse> {
  if (USE_MOCK) {
    return {
      audio_url: ""
    };
  }
  return request<TTSResponse>("/utils/tts", {
    method: "POST",
    body: JSON.stringify({
      message_id: messageId,
      text,
      voice,
      speed
    })
  });
}
