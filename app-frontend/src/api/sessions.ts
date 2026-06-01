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
}

export interface CreateSessionParams {
  character_id: number;
  parent_session_id?: number | null;
  title: string;
  greeting_index?: number;
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
      // 衍生分支从新会话层级的空消息开始（父级会话的消息历史将通过递归回溯加载）
      db.messages[newSessionId] = [];
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
  limit = 50
): Promise<GetHistoryResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    // 开启分支故事（子会话）时，不再合并父会话的历史消息，只读取本会话产生的聊天记录
    const msgs = db.messages[sessionId] || [];
    return {
      session_id: sessionId,
      messages: msgs.slice(-limit),
    };
  }

  return request<GetHistoryResponse>(
    `/sessions/${sessionId}/history?limit=${limit}`
  );
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
