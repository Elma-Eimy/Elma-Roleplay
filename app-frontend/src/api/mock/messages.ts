import type {
  Message,
  GetHistoryResponse,
  UpdateMessageResponse,
  DeleteMessageResponse,
  SwitchCandidateResponse,
} from "../../types/messages";
import { getMockDB, setMockDB } from "../config";

export async function getSessionHistory(
  sessionId: number,
  limit = 50,
  beforeId?: number
): Promise<GetHistoryResponse> {
  const db = getMockDB();
  // 开启分支故事（子会话）时，不再合并父会话的历史消息，只读取本会话产生的聊天记录
  let msgs = db.messages[sessionId] || [];
  if (beforeId !== undefined) {
    msgs = msgs.filter((m) => m.id < beforeId);
  }
  return {
    session_id: sessionId,
    messages: msgs.slice(-limit),
    is_generating: false,
  };
}

export async function updateMessage(
  messageId: number,
  content: string
): Promise<UpdateMessageResponse> {
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

export async function deleteMessage(
  messageId: number
): Promise<DeleteMessageResponse> {
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

export async function switchCandidate(
  messageId: number
): Promise<SwitchCandidateResponse> {
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
