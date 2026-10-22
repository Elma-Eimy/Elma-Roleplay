import type { CharacterBase } from "@/api/characters";

export interface CharxAsset {
  index: number;
  name: string;
  type: string;
  uri: string;
  ext: string;
  sha256: string;
}

export interface CharxPreview {
  token: string;
  expires_at: number;
  card: CharacterBase;
  assets: CharxAsset[];
  warnings: string[];
  skipped_count: number;
  package_sha256: string;
  compatibility: { status: "preserved" | "skipped" | "unknown"; label: string; count: number | null }[];
  skipped_assets: { name: string; reason: string }[];
}

export interface CharxImportRequest {
  operation: "create_character" | "append_assets";
  skip_duplicates: boolean;
  character_id: number | null;
  name: string | null;
  portrait_indices: number[];
  avatar_index: number | null;
}

export interface CharxImportResult {
  character_id: number;
  created: boolean;
  portraits_added: number;
  duplicates_skipped: number;
}

export interface CharxStatus {
  status: "parsing" | "ready" | "imported" | "cancelled" | "expired" | "not_found" | "target_deleted";
  result?: CharxImportResult;
}
