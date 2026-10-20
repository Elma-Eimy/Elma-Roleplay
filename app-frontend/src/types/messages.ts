export interface MessageCandidate {
  id: number;
  content: string;
  reasoning_content?: string | null;
  emotion_tag: string | null;
  affection_change: number | null;
  created_at: string;
  audio_path?: string | null;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  reasoning_content?: string | null;
  emotion_tag: string | null;
  affection_change: number | null;
  created_at: string;
  model_used?: string;
  parent_id?: number | null;
  is_active?: boolean;
  candidates?: MessageCandidate[];
  active_index?: number;
  audio_path?: string | null;
}

export interface GetHistoryResponse {
  session_id: number;
  messages: Message[];
  is_generating?: boolean;
}

export interface UpdateMessageResponse {
  message: string;
  message_id: number;
  content: string;
}

export interface DeleteMessageResponse {
  message: string;
  message_id: number;
  affection_score?: number | null;
  current_mood?: string | null;
}

export interface SwitchCandidateResponse {
  message: string;
  message_id: number;
  is_active: boolean;
  affection_score: number | null;
  current_mood: string | null;
}
