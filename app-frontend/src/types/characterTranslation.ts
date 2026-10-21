export interface CharacterReadingFields {
  description: string;
  personality: string;
  scenario: string;
  first_mes: string;
  mes_example: string;
  creator_notes: string;
  alternate_greetings: string[];
}

export interface CharacterTranslation {
  source_hash: string;
  model: string;
  fields: CharacterReadingFields;
  created_at: string;
}

export interface CharacterTranslationResponse {
  translation: CharacterTranslation | null;
}
