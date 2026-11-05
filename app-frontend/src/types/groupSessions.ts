import type { RoleState } from "./roleState";

export interface GroupCharacterOption {
  id: number;
  name: string;
  avatar_path: string | null;
  description?: string;
}

export type GroupMemberOrigin =
  | { mode: "card"; session_id?: null }
  | { mode: "single_snapshot"; session_id: number };

export interface CreateGroupSessionParams {
  title?: string;
  user_nickname?: string;
  shared_setting?: string | null;
  members: { character_id: number; origin: GroupMemberOrigin }[];
}

export interface GroupSessionMember {
  persona_id: number;
  slot: number;
  character: { id: number; name: string; avatar_path: string | null };
  state: {
    affection_score: number | null;
    current_mood: string | null;
    cognition_state: string | null;
    current_scenario_override: string | null;
    role_state: RoleState;
    portrait_base: number;
  };
  origin: {
    mode: "card" | "single_snapshot";
    snapshot_version: number;
    captured_at: string;
    source_session_id: number | null;
    source_persona_id: number | null;
    inherited_memory_count: number;
  };
}

export interface GroupSessionDetail {
  kind: "group";
  session_id: number;
  title: string;
  user_nickname: string;
  shared_setting: string | null;
  created_at: string;
  updated_at: string;
  can_generate: false;
  members: GroupSessionMember[];
}

export interface GetGroupSessionsResponse {
  sessions: GroupSessionDetail[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DeleteGroupSessionResponse {
  deleted_session_id: number;
  members_deleted: number;
  local_memories_deleted: number;
}

export interface GroupUtterance {
  item_id: number;
  sequence: number;
  speaker_persona_id: number;
  speaker_name: string;
  content: string;
  created_at: string;
}

export interface GroupRound {
  round_id: number;
  round_index: number;
  candidate_id: number | null;
  status: "generating" | "awaiting_confirmation" | "failed";
  confirmed: boolean;
  user_content: string;
  created_at: string;
  utterances: GroupUtterance[];
}

export interface GetGroupRoundsResponse {
  rounds: GroupRound[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
