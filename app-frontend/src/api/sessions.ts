import { request, USE_MOCK, getMockDB, setMockDB } from "./config";

// ===================== 类型定义 =====================

export interface PersonaSummary {
  id: number;
  affection_score: number;
  current_mood: string;
}

export interface PersonaDetail {
  id: number;
  character_id: number;
  affection_score: number;
  cognition_state: string;
  current_mood: string;
  current_scenario_override: string | null;
}

export interface CharacterRef {
  id: number;
  name: string;
  avatar_path: string;
}

export interface SessionSummary {
  id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  persona: PersonaSummary;
}

export interface SessionDetail {
  id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  persona: PersonaDetail;
  character: CharacterRef;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  emotion_tag: string | null;
  affection_change: number | null;
  created_at: string;
  model_used?: string;
  parent_id?: number | null;
  is_active?: boolean;
  candidates?: Message[];
  active_index?: number;
  audio_path?: string | null;
}

export interface MemoryChunk {
  id: number;
  content: string;
  memory_type: string;
  importance_score: number;
  is_local: boolean;
  created_at: string | null;
  origin_session_id?: number | null;
}

export interface CreateSessionParams {
  character_id: number;
  parent_session_id?: number | null;
  title: string;
  greeting_index?: number;
  start_message_id?: number | null;
}

export interface CreateSessionResponse {
  message: string;
  session_id: number;
  persona_id: number;
  character_id: number;
  inherited: boolean;
  title: string;
}

export interface GetSessionsResponse {
  character_id: number;
  sessions: SessionSummary[];
}

export interface GetHistoryResponse {
  session_id: number;
  messages: Message[];
}

export interface UpdateTitleResponse {
  message: string;
  session_id: number;
  title: string;
}

export interface DeleteSessionResponse {
  message: string;
  deleted_session_id: number;
  relinked_children: number;
  memories_deleted: number;
}

export interface TriggerSummaryResponse {
  message: string;
  session_id: number;
  extracted_count: number;
}

export interface TriggerCognitionResponse {
  message: string;
  session_id: number;
  cognition_state: string;
}

export interface UpdateMessageResponse {
  message: string;
  message_id: number;
  content: string;
}

export interface DeleteMessageResponse {
  message: string;
  message_id: number;
  affection_score?: number | null;
  current_mood?: string | null;
}

// ===================== API 接口函数 =====================

/**
 * 创建新会话（全新会话或继承自父会话的分支会话）。
 * POST /sessions/create
 */
export async function createSession(
  params: CreateSessionParams
): Promise<CreateSessionResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const parentSession = params.parent_session_id 
      ? db.sessions.find((s) => s.id === params.parent_session_id) 
      : null;
      
    const char = db.characters.find((c) => c.id === params.character_id);
    const newSessionId = Date.now();
    const personaId = Date.now() + 1;

    const mockPersona: PersonaDetail = {
      id: personaId,
      character_id: params.character_id,
      affection_score: parentSession ? parentSession.persona.affection_score : 10,
      cognition_state: parentSession 
        ? parentSession.persona.cognition_state 
        : "Initial acquaintance. Character is ready to chat.",
      current_mood: parentSession ? parentSession.persona.current_mood : "Calm",
      current_scenario_override: parentSession ? parentSession.persona.current_scenario_override : null,
    };

    const newSession: SessionDetail = {
      id: newSessionId,
      title: params.title || (parentSession ? `${parentSession.title} (Branch)` : "New Story"),
      parent_session_id: params.parent_session_id || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      persona: mockPersona,
      character: {
        id: params.character_id,
        name: char ? char.name : "Unknown Character",
        avatar_path: char ? char.avatar_path || "" : "",
      },
    };

    db.sessions.push(newSession);

    // 如果是全新的首个会话（无父级会话），插入角色的第一条问候消息。
    if (!params.parent_session_id) {
      db.messages[newSessionId] = [];
      let firstContent = char ? char.first_mes : "";
      if (params.greeting_index !== undefined && char && char.extensions?.alternate_greetings) {
        const alt = char.extensions.alternate_greetings as string[];
        if (params.greeting_index >= 0 && params.greeting_index < alt.length) {
          firstContent = alt[params.greeting_index];
        }
      }
      if (firstContent) {
        db.messages[newSessionId].push({
          id: Date.now() + 2,
          role: "assistant",
          content: firstContent,
          emotion_tag: "Calm",
          affection_change: 0,
          created_at: new Date().toISOString(),
        });
      }
    } else {
      // 衍生分支：复制触发分支的开头消息
      db.messages[newSessionId] = [];
      const parentSessionId = params.parent_session_id;
      if (parentSessionId) {
        let startMsg = null;
        if (params.start_message_id) {
          const parentMsgs = db.messages[parentSessionId] || [];
          startMsg = parentMsgs.find(m => m.id === params.start_message_id);
        } else {
          const parentMsgs = db.messages[parentSessionId] || [];
          if (parentMsgs.length > 0) {
            startMsg = parentMsgs[parentMsgs.length - 1];
          }
        }
        if (startMsg) {
          db.messages[newSessionId].push({
            id: Date.now() + 3,
            role: startMsg.role,
            content: startMsg.content,
            emotion_tag: startMsg.emotion_tag || "Calm",
            affection_change: startMsg.affection_change || 0,
            audio_path: startMsg.audio_path || null,
            created_at: new Date().toISOString(),
          });
        }
      }
    }

    setMockDB(db);
    return {
      message: "Session created successfully (Mock)",
      session_id: newSessionId,
      persona_id: personaId,
      character_id: params.character_id,
      inherited: !!params.parent_session_id,
      title: newSession.title,
    };
  }

  return request<CreateSessionResponse>("/sessions/create", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

/**
 * 列出指定角色的所有会话。
 * GET /sessions?character_id={characterId}
 */
export async function getSessions(characterId: number): Promise<GetSessionsResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const filtered = db.sessions.filter((s) => s.character_id === characterId);
    return {
      character_id: characterId,
      sessions: filtered.map((s) => ({
        id: s.id,
        title: s.title,
        parent_session_id: s.parent_session_id,
        created_at: s.created_at,
        updated_at: s.updated_at,
        persona: {
          id: s.persona.id,
          affection_score: s.persona.affection_score,
          current_mood: s.persona.current_mood,
        },
      })),
    };
  }

  return request<GetSessionsResponse>(`/sessions?character_id=${characterId}`);
}

/**
 * 获取指定会话的详细信息（包含人设状态数据）。
 * GET /sessions/{session_id}
 */
export async function getSession(sessionId: number): Promise<SessionDetail> {
  if (USE_MOCK) {
    const db = getMockDB();
    const session = db.sessions.find((s) => s.id === sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    return session;
  }

  return request<SessionDetail>(`/sessions/${sessionId}`);
}

/**
 * 获取感知继承关系的、按时间先后排序的会话聊天历史记录。
 * GET /sessions/{session_id}/history?limit={limit}
 */
export async function getSessionHistory(
  sessionId: number,
  limit = 50,
  beforeId?: number
): Promise<GetHistoryResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    // 开启分支故事（子会话）时，不再合并父会话的历史消息，只读取本会话产生的聊天记录
    let msgs = db.messages[sessionId] || [];
    if (beforeId !== undefined) {
      msgs = msgs.filter((m) => m.id < beforeId);
    }
    return {
      session_id: sessionId,
      messages: msgs.slice(-limit),
    };
  }

  const url = beforeId !== undefined
    ? `/sessions/${sessionId}/history?limit=${limit}&before_id=${beforeId}`
    : `/sessions/${sessionId}/history?limit=${limit}`;

  return request<GetHistoryResponse>(url);
}

/**
 * 重命名会话的标题。
 * PUT /sessions/{session_id}/title
 */
export async function updateSessionTitle(
  sessionId: number,
  title: string
): Promise<UpdateTitleResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const session = db.sessions.find((s) => s.id === sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    session.title = title;
    session.updated_at = new Date().toISOString();
    setMockDB(db);
    return {
      message: "Session title updated successfully (Mock)",
      session_id: sessionId,
      title: title,
    };
  }

  return request<UpdateTitleResponse>(`/sessions/${sessionId}/title`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

/**
 * 删除会话并安全地重联其子分支会话。
 * DELETE /sessions/{session_id} -> 改为 POST /sessions/{session_id}/delete 避开移动端及网关 DELETE 限制
 */
export async function deleteSession(
  sessionId: number
): Promise<DeleteSessionResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const targetSession = db.sessions.find((s) => s.id === sessionId);
    if (!targetSession) {
      throw new Error(`Session ${sessionId} not found`);
    }

    const parentId = targetSession.parent_session_id;

    // 将指向该会话的所有子分支会话重新链接到该会话的父级会话
    let relinkedCount = 0;
    db.sessions.forEach((s) => {
      if (s.parent_session_id === sessionId) {
        s.parent_session_id = parentId;
        relinkedCount++;
      }
    });

    db.sessions = db.sessions.filter((s) => s.id !== sessionId);
    const messagesCount = db.messages[sessionId]?.length || 0;
    delete db.messages[sessionId];

    setMockDB(db);
    return {
      message: "Session deleted successfully (Mock)",
      deleted_session_id: sessionId,
      relinked_children: relinkedCount,
      memories_deleted: messagesCount,
    };
  }

  return request<DeleteSessionResponse>(`/sessions/${sessionId}/delete`, {
    method: "POST",
  });
}

/**
 * 手动触发新消息的记忆提纯（记忆元提取）。
 * POST /sessions/{session_id}/trigger_summary
 */
export async function triggerSummary(
  sessionId: number
): Promise<TriggerSummaryResponse> {
  if (USE_MOCK) {
    return {
      message: "记忆提纯流程已完成 (Mock)",
      session_id: sessionId,
      extracted_count: 2,
    };
  }

  return request<TriggerSummaryResponse>(
    `/sessions/${sessionId}/trigger_summary`,
    { method: "POST" }
  );
}

/**
 * 手动触发更新角色微观认知状态。
 * POST /sessions/{session_id}/trigger_cognition
 */
export async function triggerCognition(
  sessionId: number
): Promise<TriggerCognitionResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const session = db.sessions.find((s) => s.id === sessionId);
    const charName = session?.character.name || "AI";
    const newCognition = `The character ${charName} feels a deeper bond with the user. Current scenario remains active.`;
    
    if (session) {
      session.persona.cognition_state = newCognition;
      setMockDB(db);
    }

    return {
      message: "认知更新已完成 (Mock)",
      session_id: sessionId,
      cognition_state: newCognition,
    };
  }

  return request<TriggerCognitionResponse>(
    `/sessions/${sessionId}/trigger_cognition`,
    { method: "POST" }
  );
}

/**
 * 修改单条消息的内容。
 * PUT /sessions/messages/{message_id}
 */
export async function updateMessage(
  messageId: number,
  content: string
): Promise<UpdateMessageResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    let updated = false;

    // 在所有会话的消息中进行检索
    for (const sid in db.messages) {
      const msgs = db.messages[sid];
      const m = msgs.find((msg) => msg.id === messageId);
      if (m) {
        m.content = content;
        updated = true;
        break;
      }
    }

    if (!updated) {
      throw new Error(`Message ${messageId} not found`);
    }

    setMockDB(db);
    return {
      message: "Message updated successfully (Mock)",
      message_id: messageId,
      content,
    };
  }

  return request<UpdateMessageResponse>(`/sessions/messages/${messageId}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

/**
 * 删除单条消息（回滚/撤销对话状态）。
 * DELETE /sessions/messages/{message_id} -> 改为 POST /sessions/messages/{message_id}/delete 避开移动端及网关限制
 */
export async function deleteMessage(
  messageId: number
): Promise<DeleteMessageResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    let deleted = false;

    for (const sid in db.messages) {
      const msgs = db.messages[sid];
      const idx = msgs.findIndex((msg) => msg.id === messageId);
      if (idx !== -1) {
        msgs.splice(idx, 1);
        deleted = true;
        break;
      }
    }

    if (!deleted) {
      throw new Error(`Message ${messageId} not found`);
    }

    setMockDB(db);
    return {
      message: "Message deleted successfully (Mock)",
      message_id: messageId,
    };
  }

  return request<DeleteMessageResponse>(`/sessions/messages/${messageId}/delete`, {
    method: "POST",
  });
}

export interface SwitchCandidateResponse {
  message: string;
  message_id: number;
  is_active: boolean;
  affection_score: number | null;
  current_mood: string | null;
}

/**
 * 切换激活的 AI 回复候选版本。
 * POST /chat/switch_candidate
 */
export async function switchCandidate(
  messageId: number
): Promise<SwitchCandidateResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    let msg: any = null;
    let sid: string = "";
    for (const key in db.messages) {
      const found = db.messages[key].find((m) => m.id === messageId);
      if (found) {
        msg = found;
        sid = key;
        break;
      }
    }
    if (msg) {
      const msgs = (db.messages as any)[sid] as any[];
      if (msgs) {
        msgs.forEach((m: any) => {
          if (m.role === "assistant" && m.parent_id === msg.parent_id) {
            m.is_active = (m.id === messageId);
          }
        });
      }
      setMockDB(db);
    }
    return {
      message: "Candidate switched successfully (Mock)",
      message_id: messageId,
      is_active: true,
      affection_score: 50,
      current_mood: msg?.emotion_tag || "Calm",
    };
  }

  return request<SwitchCandidateResponse>("/chat/switch_candidate", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId }),
  });
}

export interface MemoryCreateResponse {
  message: string;
  memory: MemoryChunk;
}

export interface MemoryUpdateResponse {
  message: string;
  memory: {
    id: number;
    content: string;
    importance_score: number;
  };
}

export interface MemoryDeleteResponse {
  message: string;
  memory_id: number;
}

/**
 * 获取会话对应的向量记忆列表。
 * GET /sessions/{session_id}/memories
 */
export async function getSessionMemories(
  sessionId: number,
  limit: number = 20,
  offset: number = 0,
  q: string = ""
): Promise<MemoryChunk[]> {
  if (USE_MOCK) {
    const db = getMockDB() as any;
    if (!db.memories) {
      db.memories = {};
    }
    let list = db.memories[sessionId] || [];
    if (q && q.trim()) {
      const term = q.trim().toLowerCase();
      list = list.filter((m: any) => m.content.toLowerCase().includes(term));
    }
    return list.slice(offset, offset + limit);
  }

  const queryParam = q && q.trim() ? `&q=${encodeURIComponent(q.trim())}` : "";
  return request<MemoryChunk[]>(`/sessions/${sessionId}/memories?limit=${limit}&offset=${offset}${queryParam}`, {
    method: "GET",
  });
}

/**
 * 手动创建向量记忆。
 * POST /sessions/{session_id}/memories
 */
export async function createSessionMemory(
  sessionId: number,
  content: string,
  importanceScore: number = 0.8
): Promise<MemoryCreateResponse> {
  if (USE_MOCK) {
    const db = getMockDB() as any;
    if (!db.memories) {
      db.memories = {};
    }
    if (!db.memories[sessionId]) {
      db.memories[sessionId] = [];
    }
    const newMemory: MemoryChunk = {
      id: Date.now(),
      content,
      memory_type: "fact",
      importance_score: importanceScore,
      is_local: true,
      created_at: new Date().toISOString(),
      origin_session_id: sessionId,
    };
    db.memories[sessionId].unshift(newMemory);
    setMockDB(db);
    return {
      message: "Memory added successfully (Mock)",
      memory: newMemory,
    };
  }

  return request<MemoryCreateResponse>(`/sessions/${sessionId}/memories`, {
    method: "POST",
    body: JSON.stringify({
      content,
      importance_score: importanceScore,
      memory_type: "fact",
    }),
  });
}

/**
 * 更新向量记忆。
 * PUT /sessions/{session_id}/memories/{memory_id}
 */
export async function updateSessionMemory(
  sessionId: number,
  memoryId: number,
  content: string,
  importanceScore: number
): Promise<MemoryUpdateResponse> {
  if (USE_MOCK) {
    const db = getMockDB() as any;
    if (!db.memories) {
      db.memories = {};
    }
    const list = db.memories[sessionId] || [];
    const item = list.find((m: any) => m.id === memoryId);
    if (item) {
      item.content = content;
      item.importance_score = importanceScore;
      setMockDB(db);
    }
    return {
      message: "Memory updated successfully (Mock)",
      memory: {
        id: memoryId,
        content,
        importance_score: importanceScore,
      },
    };
  }

  return request<MemoryUpdateResponse>(`/sessions/${sessionId}/memories/${memoryId}`, {
    method: "PUT",
    body: JSON.stringify({
      content,
      importance_score: importanceScore,
    }),
  });
}

/**
 * 删除向量记忆。
 * DELETE /sessions/{session_id}/memories/{memory_id}
 */
export async function deleteSessionMemory(
  sessionId: number,
  memoryId: number
): Promise<MemoryDeleteResponse> {
  if (USE_MOCK) {
    const db = getMockDB() as any;
    if (!db.memories) {
      db.memories = {};
    }
    const list = db.memories[sessionId] || [];
    const idx = list.findIndex((m: any) => m.id === memoryId);
    if (idx !== -1) {
      list.splice(idx, 1);
      setMockDB(db);
    }
    return {
      message: "Memory deleted successfully (Mock)",
      memory_id: memoryId,
    };
  }

  return request<MemoryDeleteResponse>(`/sessions/${sessionId}/memories/${memoryId}`, {
    method: "DELETE",
  });
}

/**
 * 获取当前会话最近编译组装好的提示词。
 * GET /sessions/{session_id}/compile_prompt
 */
export async function getCompiledPrompt(
  sessionId: number
): Promise<{ messages: { role: string; content: string }[] }> {
  if (USE_MOCK) {
    return {
      messages: [
        { role: "system", content: "【系统提示词（编译预设）】\n你扮演Cyber Hacker...\n\n【重要：输出格式要求】\n<reply>回复内容</reply>\n<status emotion=\"开心\" affection_change=\"0\"/>" },
        { role: "assistant", content: "<reply>你好，我是赛博黑客。找我有什么事？</reply>\n<status emotion=\"平静\" affection_change=\"0\"/>" },
        { role: "user", content: "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】\n<current_scenario>\n赛博朋克霓虹城市酒吧。\n</current_scenario>\n\n【当前用户的最新消息：】\n你好，请帮我分析一下这个系统漏洞。" }
      ]
    };
  }

  return request<{ messages: { role: string; content: string }[] }>(`/sessions/${sessionId}/compile_prompt`);
}
