import type { Message } from "./messages";

export interface MemoryChunk {
  id: number;
  content: string;
  memory_type: string;
  importance_score: number;
  is_local: boolean;
  created_at: string | null;
  origin_session_id?: number | null;
  source_start_message_id?: number | null;
  source_message_id?: number | null;
  supersedes_id?: number | null;
  is_superseded?: boolean;
}

export type MemoryScope = "all" | "local" | "inherited";

export type MemoryStatus = "active" | "superseded" | "all";

export interface MemoryStats {
  effective_total: number;
  local_active: number;
  inherited_active: number;
  superseded: number;
}

export interface GetSessionMemoriesParams {
  q?: string;
  scope?: MemoryScope;
  status?: MemoryStatus;
  limit?: number;
  offset?: number;
}

export interface GetSessionMemoriesResponse {
  items: MemoryChunk[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  facets: MemoryStats;
}

export interface CharacterMemoryOverviewSession {
  session_id: number;
  title: string;
  parent_session_id: number | null;
  created_at: string;
  updated_at: string;
  last_message: Pick<Message, "content" | "created_at"> | null;
  memory_stats: MemoryStats;
}

export interface CharacterMemoryOverviewResponse {
  character_id: number;
  story_count: number;
  recent_session_id: number | null;
  sessions: CharacterMemoryOverviewSession[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface TriggerSummaryResponse {
  message: string;
  session_id: number;
  extracted_count: number;
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
    source_start_message_id?: number | null;
    source_message_id?: number | null;
    supersedes_id?: number | null;
  };
}

export interface MemoryDeleteResponse {
  message: string;
  memory_id: number;
}
