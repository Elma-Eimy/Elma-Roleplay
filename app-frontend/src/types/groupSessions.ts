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
  members: { character_id: number; origin: GroupMemberOrigin; greeting_index?: number | null; greeting_content?: string | null }[];
}

export interface GroupSessionMember {
  persona_id: number;
  slot: number;
  greeting_content?: string | null;
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
  can_generate: boolean;
  group_revision?: number;
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
  revision?: number | null;
  finish_reason?: "wait_user" | "no_visible_basis" | "step_limit" | null;
  error_code?: string | null;
  user_content: string;
  created_at: string;
  utterances: GroupUtterance[];
  pending_candidate?: { candidate_id: number; status: "generating" | "failed";
    error_code: string | null; utterances: GroupUtterance[] } | null;
  portraits?: GroupMemberPortrait[];
}

export interface GetGroupRoundsResponse {
  can_generate?: boolean;
  current?: GroupCurrentState;
  rounds: GroupRound[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export type GroupOperationKind = "send" | "regenerate" | "resume" | "select" | "discard";
export type GroupOperationStatus = "queued" | "running" | "succeeded" | "failed";
export interface GroupObservedCommand {
  client_request_id: string;
  expected_group_revision: number;
  observed_round_id?: number | null;
  observed_candidate_id?: number | null;
  observed_candidate_revision?: number | null;
}
export interface GroupRoundCommand extends GroupObservedCommand {
  observed_round_id: number;
  observed_candidate_id: number;
  observed_candidate_revision: number;
}
export interface GroupGenerationOptions {
  model?: string | null;
  thinking_mode?: "inherit" | "enabled" | "disabled" | null;
  reasoning_effort?: string | null;
  max_steps?: number;
}
export interface SendGroupRoundParams extends GroupObservedCommand, GroupGenerationOptions { user_content: string }
export interface RegenerateGroupRoundParams extends GroupRoundCommand, GroupGenerationOptions {}
export interface GroupCandidateCommand extends GroupRoundCommand {
  target_candidate_id: number;
  target_candidate_revision: number;
}
export interface GroupAcceptedOperation {
  operation_id: number;
  request_id: string;
  kind: GroupOperationKind;
  status: GroupOperationStatus;
  accepted: { round_id: number; candidate_id: number; group_revision: number; candidate_revision: number; kind: GroupOperationKind };
}
export interface GroupOperationSummary {
  operation_id: number; request_id: string; kind: GroupOperationKind; status: GroupOperationStatus;
  revision: number; round_id: number; candidate_id: number; call_count: number; call_limit: number;
  created_at: string; started_at: string | null; deadline_at: string | null; finished_at: string | null;
  error_code: string | null;
}
export interface GroupCurrentState {
  group_revision: number;
  latest: { round_id: number; candidate_id: number | null; candidate_revision: number | null; confirmed: boolean } | null;
  active_operation: GroupOperationSummary | null;
  capabilities: { can_send: boolean; can_regenerate: boolean; can_select: boolean; can_discard: boolean };
}
export interface GroupCandidateSummary {
  candidate_id: number; version: number; revision: number;
  status: GroupRound["status"]; checkpoint: "user_visibility" | "next_action" | "role_generation" | "finish" | "done" | null;
  protocol_version: 1 | 2; selected: boolean; finish_reason: GroupRound["finish_reason"];
  error_code: string | null; can_select: boolean; can_resume: boolean;
}
export interface GroupRoundSummary {
  round_id: number; round_index: number; user_content: string; selected_candidate_id: number | null;
  confirmed: boolean; discarded_at: string | null; created_at: string;
}
export interface GetGroupCandidatesResponse {
  can_generate: boolean; round: GroupRoundSummary; candidates: GroupCandidateSummary[]; current: GroupCurrentState;
  total: number; limit: number; offset: number; has_more: boolean;
}
export interface GetGroupCandidateResponse {
  can_generate: boolean; round: GroupRoundSummary; candidate: GroupCandidateSummary; current: GroupCurrentState;
  utterances: GroupUtterance[];
  state_preview: { candidate_id: number; members: GroupCandidateMemberState[] };
}
export interface GroupMemberInsight {
  kind: "cognition" | "user" | "member";
  content: string;
  target_persona_id: number | null;
  target_name: string | null;
}
export interface GroupCandidateMemberState {
  persona_id: number;
  affection_score: number;
  current_mood: string | null;
  role_state: RoleState;
  cognition_state?: string | null;
  insights?: GroupMemberInsight[];
  portrait?: GroupMemberPortrait;
}
export interface GroupMemberPortrait {
  persona_id: number;
  portrait_id: number | null;
  image_path: string;
}
export interface GroupPortraitsResponse {
  session_id: number;
  current: GroupCurrentState;
  can_update: boolean;
  members: GroupMemberPortrait[];
}
export type GroupPortraitChange = Omit<GroupObservedCommand, "client_request_id"> & { portrait_id: number | null };
export interface GetGroupRequestResponse extends GroupOperationSummary {
  can_generate: boolean; accepted: GroupAcceptedOperation["accepted"];
  round: GroupRoundSummary; candidate: GroupCandidateSummary; current: GroupCurrentState;
}

export interface GroupPromptPreview {
  messages: { role: string; content: string }[];
  token_estimate: import("@/api/sessions").TokenEstimate;
  candidate_id: number;
  revision: number;
}
