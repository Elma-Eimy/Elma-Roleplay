import { ref, watch } from "vue";
import { useChatStore } from "@/store/chatStore";
import type { ActiveStreamRequest, StreamBridgeEvent } from "@/types/chatStream";

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
    { deep: true, immediate: true, flush: "sync" }
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
      (!currentStreamRequestId.value || payload.requestId !== currentStreamRequestId.value)
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
      resetStreamBridge();
      const meta = payload.meta ?? {};
      chatStore.completeStream(
        payload.placeholderId,
        meta,
        payload.userMessageTempId
      );
      return;
    }

    if (payload.type === "error") {
      resetStreamBridge();
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
