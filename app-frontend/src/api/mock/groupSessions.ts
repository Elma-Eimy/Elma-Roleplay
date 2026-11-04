import { getMockDB, setMockDB } from "../config";
import type { MockDatabase } from "../config";
import type { CreateGroupSessionParams, GroupSessionDetail, GetGroupSessionsResponse,
  DeleteGroupSessionResponse } from "../../types/groupSessions";

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

function requireGroup(db: MockDatabase, sessionId: number): GroupSessionDetail {
  if (db.sessions.some(session => session.id === sessionId)) {
    throw new Error("此操作仅支持群聊");
  }
  const group = db.groupSessions?.find(session => session.session_id === sessionId);
  if (!group) throw new Error("群聊不存在");
  return group;
}

export async function createGroupSession(params: CreateGroupSessionParams): Promise<GroupSessionDetail> {
  if (!Array.isArray(params.members) || params.members.length < 2 || params.members.length > 3) {
    throw new Error("群聊需要 2–3 个 AI 成员");
  }
  const title = (params.title ?? "新的群聊").trim();
  const nickname = (params.user_nickname ?? "用户").trim();
  if (!title || title.length > 50 || !nickname || nickname.length > 50) {
    throw new Error("标题和昵称需要 1–50 字");
  }
  if ((params.shared_setting?.length ?? 0) > 20000) throw new Error("共同设定最多 20000 字");
  const ids = params.members.map(member => member.character_id);
  if (ids.some(id => !Number.isInteger(id) || id <= 0) || new Set(ids).size !== ids.length) {
    throw new Error("成员角色 ID 无效或重复");
  }
  for (const member of params.members) {
    if (member.origin?.mode === "single_snapshot") {
      throw new Error("离线模式暂不支持导入单聊状态与记忆快照");
    }
    if (member.origin?.mode !== "card" || member.origin.session_id != null) {
      throw new Error("原卡起步不能指定来源故事");
    }
  }
  const db = getMockDB();
  const characters = params.members.map(member => db.characters.find(character => character.id === member.character_id));
  if (characters.some(character => !character)) throw new Error("成员角色不存在");
  const groups = db.groupSessions ?? [];
  const sessionId = Math.max(Date.now(), ...db.sessions.map(session => session.id), ...groups.map(group => group.session_id)) + 1;
  const personaId = Math.max(Date.now(), ...db.sessions.map(session => session.persona?.id ?? 0),
    ...groups.flatMap(group => group.members.map(member => member.persona_id))) + 1;
  const now = new Date().toISOString();
  const group: GroupSessionDetail = {
    kind: "group", session_id: sessionId, title, user_nickname: nickname,
    shared_setting: params.shared_setting?.trim() || null,
    created_at: now, updated_at: now, can_generate: false,
    members: characters.map((character, index) => ({
      persona_id: personaId + index, slot: index + 1,
      character: { id: character.id, name: character.name, avatar_path: character.avatar_path ?? null },
      state: { affection_score: 0, current_mood: null, cognition_state: null,
        current_scenario_override: null, role_state: {}, portrait_base: 0 },
      origin: { mode: "card", snapshot_version: 1, captured_at: now,
        source_session_id: null, source_persona_id: null, inherited_memory_count: 0 },
    })),
  };
  setMockDB({ ...db, groupSessions: [...groups, group] });
  return clone(group);
}

export async function getGroupSessions(limit = 20, offset = 0): Promise<GetGroupSessionsResponse> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0) {
    throw new Error("分页参数无效");
  }
  const groups = [...(getMockDB().groupSessions ?? [])].sort((a, b) =>
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() || b.session_id - a.session_id);
  const sessions = groups.slice(offset, offset + limit);
  return clone({ sessions, total: groups.length, limit, offset, has_more: offset + sessions.length < groups.length });
}

export async function getGroupSession(sessionId: number): Promise<GroupSessionDetail> {
  return clone(requireGroup(getMockDB(), sessionId));
}

export async function deleteGroupSession(sessionId: number): Promise<DeleteGroupSessionResponse> {
  const db = getMockDB();
  const group = requireGroup(db, sessionId);
  setMockDB({ ...db, groupSessions: db.groupSessions!.filter(session => session.session_id !== sessionId) });
  return { deleted_session_id: sessionId, members_deleted: group.members.length, local_memories_deleted: 0 };
}
