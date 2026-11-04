import type { SessionSummary } from "@/api/sessions";

export type MessageActionResult =
  | { status: "success" }
  | { status: "stale" }
  | { status: "error"; message: string };

export interface BranchSession extends SessionSummary {
  lastMessage: string;
  lastMessageTime: string;
}
