export interface CharacterBase {
  name: string;
  avatar_path?: string;
  description: string;
  personality?: string;
  scenario?: string;
  first_mes?: string;
  mes_example?: string;
  creator_notes?: string;
  system_prompt_override?: string;
  post_history_instructions?: string;
  tags?: string[];
  extensions?: Record<string, unknown>;
}

export interface CharacterSummary {
  id: number;
  name: string;
  avatar_path: string;
  description: string;
  creator?: string;
}

export interface CharacterDetail extends CharacterBase {
  id: number;
  created_at: string;
  lorebooks?: { id: number; name: string }[];
}

export interface ParsedCharacterData extends CharacterBase {}

export interface ParseCharacterResponse {
  message: string;
  data: ParsedCharacterData;
}

export interface CreateCharacterResponse {
  message: string;
  character_id: number;
  name: string;
  created?: boolean;
}

export interface UpdateCharacterResponse {
  message: string;
  character_id: number;
  name: string;
}

export interface DeleteCharacterResponse {
  message: string;
  character_id: number;
  sessions_deleted_count: number;
}

export interface UploadAvatarResponse {
  message: string;
  avatar_path: string;
}

export interface GetCharactersResponse {
  characters: CharacterSummary[];
}
