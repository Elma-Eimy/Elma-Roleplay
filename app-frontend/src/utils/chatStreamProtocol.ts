import { createSSEParser } from "./sse";
import type { ChatResponse } from "../api/chat";

export interface StreamCallbacks {
  chunk: (text: string) => void;
  reasoning?: (text: string) => void;
  done: (meta: Omit<ChatResponse, "reply">) => void;
  error: (error: Error) => void;
}

/** Shared wire protocol for fetch, uni.request and App renderjs transports. */
export function createChatStreamProtocol(callbacks: StreamCallbacks, cancelled = () => false) {
  let terminal = false;
  const fail = (error: unknown) => {
    if (terminal || cancelled()) return;
    terminal = true;
    callbacks.error(error instanceof Error ? error : new Error(String(error)));
  };
  const parser = createSSEParser((raw) => {
    if (terminal || cancelled() || raw.trim() === "[DONE]") return;
    const payload = JSON.parse(raw);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("Invalid SSE response");
    }
    if (payload.error !== undefined) fail(new Error(String(payload.error)));
    else if (typeof payload.chunk === "string") callbacks.chunk(payload.chunk);
    else if (typeof payload.reasoning_chunk === "string") callbacks.reasoning?.(payload.reasoning_chunk);
    else {
      terminal = true;
      callbacks.done(payload);
    }
  });
  return {
    get finished() { return terminal; },
    fail,
    push(text: string) {
      if (terminal || cancelled()) return;
      try { parser.push(text); } catch (error) { fail(error); }
    },
    finish() {
      if (terminal || cancelled()) return;
      try {
        parser.finish();
        if (!terminal) fail(new Error("连接已结束，但未收到完整回复，请重试"));
      } catch (error) { fail(error); }
    },
  };
}
