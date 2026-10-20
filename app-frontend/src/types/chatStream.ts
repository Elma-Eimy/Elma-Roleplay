import type { ChatRequest, ChatResponse } from "../api/chat";
import type { MessageCandidate } from "../api/sessions";

export interface ActiveStreamRequest {
  requestId: string;
  placeholderId: string;
  userMessageTempId?: string;
  params: ChatRequest;
  baseUrl: string;
  apiKey: string;
  timestamp: number;
}

type StreamMeta = Partial<Omit<ChatResponse, "reply">> & {
  candidates?: MessageCandidate[];
};

export type StreamPayload =
  | {
      type: "chunk";
      requestId: string;
      placeholderId: string;
      chunk: string;
    }
  | {
      type: "reasoning_chunk";
      requestId: string;
      placeholderId: string;
      reasoning_chunk: string;
    }
  | {
      type: "done";
      requestId: string;
      placeholderId: string;
      userMessageTempId?: string;
      meta?: StreamMeta;
    }
  | {
      type: "error";
      requestId: string;
      placeholderId: string;
      userMessageTempId?: string;
      error?: string;
    }
  | {
      type: "log";
      level?: "error" | "warn" | "info";
      message?: string;
    };

export interface StreamBridgeEvent {
  detail?: StreamPayload;
}
