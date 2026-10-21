import { createChatStreamProtocol } from "../../utils/chatStreamProtocol";
import type { ActiveStreamRequest, StreamPayload } from "../../types/chatStream";

export function createAppStreamTransport(
  createXHR: () => XMLHttpRequest,
  emit: (payload: StreamPayload) => void
) {
  let current: { requestId: string; cancel: () => void } | null = null;
  const cancel = () => {
    const previous = current;
    current = null;
    previous?.cancel();
  };
  return {
    cancel,
    start(request: ActiveStreamRequest | null) {
      if (request && current?.requestId === request.requestId) return;
      cancel();
      if (!request) return;
      let xhr: XMLHttpRequest | undefined;
      let cursor = 0;
      const run = { requestId: request.requestId, cancel: () => xhr?.abort() };
      current = run;
      const live = () => current === run;
      const identity = {
        requestId: request.requestId, placeholderId: request.placeholderId,
        userMessageTempId: request.userMessageTempId,
      };
      const protocol = createChatStreamProtocol({
        chunk: (chunk) => emit({ ...identity, type: "chunk", chunk }),
        reasoning: (reasoning_chunk) => emit({ ...identity, type: "reasoning_chunk", reasoning_chunk }),
        done: (meta) => emit({ ...identity, type: "done", meta }),
        error: (error) => emit({ ...identity, type: "error", error: error.message }),
      }, () => !live());
      const close = () => {
        if (!live()) return;
        current = null;
        // Invalidate before abort: some WebViews invoke abort handlers synchronously.
        xhr?.abort();
      };
      const read = () => {
        if (!live() || !xhr || xhr.status < 200 || xhr.status >= 300) return;
        const text = xhr.responseText;
        protocol.push(text.slice(cursor));
        cursor = text.length;
      };
      const fail = (error: unknown) => {
        if (!live()) return;
        protocol.fail(error);
        close();
      };
      try {
        xhr = createXHR();
        xhr.open("POST", `${request.baseUrl.replace(/\/$/, "")}/chat/stream`, true);
        xhr.setRequestHeader("Content-Type", "application/json");
        if (request.apiKey) xhr.setRequestHeader("X-API-Key", request.apiKey);
        xhr.onprogress = () => {
          if (!live()) return;
          try { read(); if (protocol.finished) close(); }
          catch (error) { fail(error); }
        };
        xhr.onload = () => {
          if (!live()) return;
          try {
            if (xhr!.status < 200 || xhr!.status >= 300) {
              throw new Error(`SSE connection failed: ${xhr!.status}`);
            }
            read();
            protocol.finish();
            close();
          } catch (error) { fail(error); }
        };
        xhr.onerror = () => fail(new Error("网络连接失败，请重试"));
        xhr.ontimeout = () => fail(new Error("连接超时，请重试"));
        xhr.onabort = () => fail(new Error("连接已中断，请重试"));
        xhr.send(JSON.stringify(request.params));
      } catch (error) { fail(error); }
    },
  };
}

/** Each renderjs component owns its transport; no DOM IDs or shared XHR state. */
export function createRenderjsStreamBridge() {
  const transports = new WeakMap<object, ReturnType<typeof createAppStreamTransport>>();
  function dispose(this: object) {
    transports.get(this)?.cancel();
    transports.delete(this);
  }
  return {
    beforeDestroy: dispose,
    beforeUnmount: dispose,
    methods: {
      onStreamRequestChange(this: object, request: ActiveStreamRequest | null, _previous: unknown,
        owner: { callMethod: (name: string, payload: StreamPayload) => void }) {
        let transport = transports.get(this);
        if (!transport) {
          transport = createAppStreamTransport(() => new XMLHttpRequest(),
            (payload) => owner.callMethod("onStreamEvent", payload));
          transports.set(this, transport);
        }
        transport.start(request);
      },
    },
  };
}
