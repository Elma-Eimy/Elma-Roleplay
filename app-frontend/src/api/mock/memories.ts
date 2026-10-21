import type {
  MemoryChunk,
  MemoryStats,
  GetSessionMemoriesParams,
  GetSessionMemoriesResponse,
  CharacterMemoryOverviewResponse,
  TriggerSummaryResponse,
  MemoryCreateResponse,
  MemoryUpdateResponse,
  MemoryDeleteResponse,
} from "../../types/memories";
import { getMockDB, setMockDB } from "../config";
import { getSessions } from "./sessions";

export async function triggerSummary(
  sessionId: number
): Promise<TriggerSummaryResponse> {
  return {
    message: "记忆提纯流程已完成 (Mock)",
    session_id: sessionId,
    extracted_count: 2,
  };
}

export async function getSessionMemories(
  sessionId: number,
  params: GetSessionMemoriesParams = {}
): Promise<GetSessionMemoriesResponse> {
  const {
    q = "",
    scope = "all",
    status = "active",
    limit = 20,
    offset = 0,
  } = params;

  const db = getMockDB() as any;
  if (!db.memories) {
    db.memories = {};
  }
  const sessionById = new Map<number, any>(
    (db.sessions || []).map((session: any) => [session.id, session])
  );
  const lineageSessionIds: number[] = [];
  const visited = new Set<number>();
  let currentSessionId: number | null = sessionId;
  while (currentSessionId !== null && !visited.has(currentSessionId)) {
    visited.add(currentSessionId);
    lineageSessionIds.push(currentSessionId);
    currentSessionId = sessionById.get(currentSessionId)?.parent_session_id ?? null;
  }

  let list: MemoryChunk[] = lineageSessionIds.flatMap((visibleSessionId) =>
    (db.memories[visibleSessionId] || []).map((memory: MemoryChunk) => ({
      ...memory,
      is_local: visibleSessionId === sessionId,
    }))
  );
  const supersededIds = new Set<number>(
    list
      .map((memory) => memory.supersedes_id)
      .filter((id): id is number => typeof id === "number")
  );
  list = list.map((memory) => ({
    ...memory,
    is_superseded: supersededIds.has(memory.id),
  }));

  if (q && q.trim()) {
    const term = q.trim().toLowerCase();
    list = list.filter((memory) => memory.content.toLowerCase().includes(term));
  }

  const activeList = list.filter((memory) => !memory.is_superseded);
  const facets: MemoryStats = {
    effective_total: activeList.length,
    local_active: activeList.filter((memory) => memory.is_local).length,
    inherited_active: activeList.filter((memory) => !memory.is_local).length,
    superseded: list.filter((memory) => memory.is_superseded).length,
  };

  if (scope === "local") {
    list = list.filter((memory) => memory.is_local);
  } else if (scope === "inherited") {
    list = list.filter((memory) => !memory.is_local);
  }
  if (status === "active") {
    list = list.filter((memory) => !memory.is_superseded);
  } else if (status === "superseded") {
    list = list.filter((memory) => memory.is_superseded);
  }

  list.sort((a, b) => {
    const timeDiff =
      new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    return timeDiff || b.id - a.id;
  });
  const items = list.slice(offset, offset + limit);
  return {
    items,
    total: list.length,
    limit,
    offset,
    has_more: offset + items.length < list.length,
    facets,
  };
}

export async function getCharacterMemoryOverview(
  characterId: number,
  limit = 50,
  offset = 0
): Promise<CharacterMemoryOverviewResponse> {
  const page = await getSessions(characterId, limit, offset, true);
  const sessions = await Promise.all(
    page.sessions.map(async (session) => {
      const memories = await getSessionMemories(session.id, {
        scope: "all",
        status: "active",
        limit: 1,
        offset: 0,
      });
      return {
        session_id: session.id,
        title: session.title,
        parent_session_id: session.parent_session_id,
        created_at: session.created_at,
        updated_at: session.updated_at,
        last_message: session.last_message,
        memory_stats: memories.facets,
      };
    })
  );
  return {
    character_id: characterId,
    story_count: page.total,
    recent_session_id: sessions[0]?.session_id ?? null,
    sessions,
    total: page.total,
    limit,
    offset,
    has_more: page.has_more,
  };
}

export async function createSessionMemory(
  sessionId: number,
  content: string,
  importanceScore: number = 0.8
): Promise<MemoryCreateResponse> {
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

export async function updateSessionMemory(
  sessionId: number,
  memoryId: number,
  content: string,
  importanceScore: number
): Promise<MemoryUpdateResponse> {
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

export async function deleteSessionMemory(
  sessionId: number,
  memoryId: number
): Promise<MemoryDeleteResponse> {
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
