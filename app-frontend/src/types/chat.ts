import type { SessionSummary } from "@/api/sessions";

export interface BranchSession extends SessionSummary {
  lastMessage: string;
  lastMessageTime: string;
}
