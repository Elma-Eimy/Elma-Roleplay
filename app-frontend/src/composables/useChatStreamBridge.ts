import { ref, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import type { ActiveStreamRequest } from "@/store/chatStore";
import type { ChatResponse } from "@/api/chat";
import type { MessageCandidate } from "@/api/sessions";

type StreamMeta = Partial<Omit<ChatResponse, "reply">> & {
  candidates?: MessageCandidate[];
};

type StreamPayload =
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

export function useChatStreamBridge() {
  const chatStore = useChatStore();
  const localStreamRequest = ref<ActiveStreamRequest | null>(null);
  const currentStreamRequestId = ref<string | null>(null);

  watch(
    () => chatStore.activeStreamRequest,
    (request) => {
      localStreamRequest.value = request
        ? (JSON.parse(JSON.stringify(request)) as ActiveStreamRequest)
        : null;
      currentStreamRequestId.value = request?.requestId ?? null;
    },
    { deep: true, immediate: true }
  );

  const resetStreamBridge = () => {
    localStreamRequest.value = null;
    currentStreamRequestId.value = null;
  };

  const onBridgeMessage = (event: StreamBridgeEvent) => {
    const payload = event.detail;
    if (!payload) return;

    if (
      payload.type !== "log" &&
      payload.requestId !== currentStreamRequestId.value
    ) {
      console.warn(
        `[chat stream] Ignored orphaned ${payload.type} event due to request ID mismatch.`
      );
      return;
    }

    if (payload.type === "chunk") {
      chatStore.appendStreamChunk(payload.placeholderId, payload.chunk);
      return;
    }

    if (payload.type === "reasoning_chunk") {
      chatStore.appendStreamReasoningChunk(
        payload.placeholderId,
        payload.reasoning_chunk
      );
      return;
    }

    if (payload.type === "done") {
      const meta = payload.meta ?? {};
      chatStore.completeStream(
        payload.placeholderId,
        meta,
        payload.userMessageTempId
      );
      return;
    }

    if (payload.type === "error") {
      const errorMessage = payload.error || "Failed to get AI response";
      chatStore.failStream(
        payload.placeholderId,
        errorMessage,
        payload.userMessageTempId
      );
      uni.showToast({ title: payload.error || "获取回复失败", icon: "none" });
      return;
    }

    if (payload.level === "error") {
      console.error("[WebView]", payload.message);
    } else if (payload.level === "warn") {
      console.warn("[WebView]", payload.message);
    } else {
      console.log("[WebView]", payload.message);
    }
  };

  return {
    localStreamRequest,
    onBridgeMessage,
    resetStreamBridge,
  };
}
