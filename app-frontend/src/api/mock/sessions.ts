import type {
  PersonaDetail,
  SessionDetail,
  CreateSessionParams,
  CreateSessionResponse,
  GetSessionsResponse,
  GetRecentSessionsResponse,
  UpdateTitleResponse,
  DeleteSessionResponse,
  TriggerCognitionResponse,
} from "../../types/sessions";
import { getMockDB, setMockDB } from "../config";

export async function createSession(
  params: CreateSessionParams
): Promise<CreateSessionResponse> {
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

export async function getSessions(
  characterId: number,
  limit = 50,
  offset = 0,
  includeLastMessage = true
): Promise<GetSessionsResponse> {
  const db = getMockDB();
  const filtered = db.sessions
    .filter((s) => s.character_id === characterId)
    .sort((a, b) => {
      const timeDiff = new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      return timeDiff || b.id - a.id;
    });
  const page = filtered.slice(offset, offset + limit);
  return {
    character_id: characterId,
    sessions: page.map((s) => {
      const activeMessages = (db.messages[s.id] || []).filter(
        (message) => message.is_active !== false
      );
      const lastMessage = includeLastMessage
        ? activeMessages[activeMessages.length - 1] || null
        : null;
      return {
        id: s.id,
        title: s.title,
        parent_session_id: s.parent_session_id,
        fork_message_id: s.fork_message_id || null,
        created_at: s.created_at,
        updated_at: s.updated_at,
        persona: {
          id: s.persona.id,
          affection_score: s.persona.affection_score,
          current_mood: s.persona.current_mood,
        },
        last_message: lastMessage
          ? {
              content: String(lastMessage.content || ""),
              created_at: lastMessage.created_at,
            }
          : null,
      };
    }),
    total: filtered.length,
    limit,
    offset,
    has_more: offset + page.length < filtered.length,
  };
}

export async function getRecentSessions(
  limit = 50,
  offset = 0
): Promise<GetRecentSessionsResponse> {
  const db = getMockDB();
  const sessions = db.sessions
    .map((session) => {
      const character = db.characters.find((item) => item.id === session.character_id);
      const messages = db.messages[session.id] || [];
      const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;

      return {
        id: session.id,
        title: session.title,
        parent_session_id: session.parent_session_id,
        created_at: session.created_at,
        updated_at: session.updated_at,
        persona: {
          id: session.persona.id,
          affection_score: session.persona.affection_score,
          current_mood: session.persona.current_mood,
        },
        character: {
          id: character?.id ?? session.character_id,
          name: character?.name ?? "Unknown Character",
          avatar_path: character?.avatar_path ?? "",
        },
        last_message: lastMessage
          ? {
              content: String(lastMessage.content || ""),
              created_at: lastMessage.created_at,
            }
          : null,
      };
    })
    .sort((a, b) => {
      const aTime = a.last_message?.created_at || a.updated_at;
      const bTime = b.last_message?.created_at || b.updated_at;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });

  return {
    sessions: sessions.slice(offset, offset + limit),
    total: sessions.length,
    limit,
    offset,
    has_more: offset + limit < sessions.length,
  };
}

export async function getSession(sessionId: number): Promise<SessionDetail> {
  const db = getMockDB();
  const session = db.sessions.find((s) => s.id === sessionId);
  if (!session) {
    throw new Error(`Session ${sessionId} not found`);
  }
  return session;
}

export async function updateSessionTitle(
  sessionId: number,
  title: string
): Promise<UpdateTitleResponse> {
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

export async function deleteSession(
  sessionId: number
): Promise<DeleteSessionResponse> {
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

export async function triggerCognition(
  sessionId: number
): Promise<TriggerCognitionResponse> {
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
