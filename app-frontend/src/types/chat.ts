import type { MessageCandidate } from "./messages";
import type { SessionSummary } from "./sessions";

export type MessageActionResult =
  | { status: "success" }
  | { status: "stale" }
  | { status: "error"; message: string };

export interface BranchSession extends SessionSummary {
  lastMessage: string;
  lastMessageTime: string;
}

export interface BranchTreeSession {
  id: number;
  title: string;
  parent_session_id: number | null;
  fork_message_id?: number | null;
  created_at: string;
  updated_at: string;
  persona?: {
    id: number;
    affection_score?: number;
    current_mood?: string;
  };
  lastMessage?: string;
  last_message?: { content: string; created_at: string } | null;
}

export interface BranchTreeNodeData extends BranchTreeSession {
  children: BranchTreeNodeData[];
  depth: number;
}

export interface ChatRequest {
  model?: string;
  thinking_mode?: "inherit" | "enabled" | "disabled";
  reasoning_effort?: string;
  session_id: number;
  user_message: string;
  use_reasoning?: boolean;
  is_regenerate?: boolean;
  user_nickname?: string;
  temperature?: number;
  top_p?: number;
  presence_penalty?: number;
  frequency_penalty?: number;
  repetition_penalty?: number;
}

export interface ChatResponse {
  reply: string;
  emotion_tag: string;
  affection_change: number;
  affection_score: number;
  model_used?: string;
  user_message_id?: number;
  assistant_message_id?: number;
  candidates?: MessageCandidate[];
  active_index?: number;
}
