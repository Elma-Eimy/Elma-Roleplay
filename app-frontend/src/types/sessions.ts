import type { Message } from "./messages";

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
  fork_message_id?: number | null;
  created_at: string;
  updated_at: string;
  persona: PersonaSummary;
  last_message: Pick<Message, "content" | "created_at"> | null;
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
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface RecentSessionSummary extends SessionSummary {
  character: CharacterRef;
  last_message: Pick<Message, "content" | "created_at"> | null;
}

export interface GetRecentSessionsResponse {
  sessions: RecentSessionSummary[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
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

export interface TriggerCognitionResponse {
  message: string;
  session_id: number;
  cognition_state: string;
}
