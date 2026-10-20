import { createCancellation } from "../utils/cancellation";
import type { Cancellation } from "../utils/cancellation";
import { createSSEParser, createUtf8Decoder } from "../utils/sse";
import type { ChatRequest, ChatResponse } from "./chat";

interface StreamCallbacks {
  chunk: (text: string) => void;
  reasoning?: (text: string) => void;
  done: (meta: Omit<ChatResponse, "reply">) => void;
  error: (error: Error) => void;
}

export async function receiveChatStream(
  url: string,
  headers: Record<string, string>,
  params: ChatRequest,
  callbacks: StreamCallbacks,
  cancellation: Cancellation = createCancellation()
): Promise<void> {
  if (cancellation.cancelled) return;
  let terminal = false;
  const fail = (error: unknown) => {
    if (terminal || cancellation.cancelled) return;
    terminal = true;
    callbacks.error(error instanceof Error ? error : new Error(String(error)));
  };
  const parser = createSSEParser((raw) => {
    if (terminal || cancellation.cancelled || raw.trim() === "[DONE]") return;
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
  const decoder = createUtf8Decoder();
  const feed = (data: string | ArrayBuffer | Uint8Array) => {
    if (terminal || cancellation.cancelled) return;
    parser.push(typeof data === "string" ? data : decoder.push(data instanceof Uint8Array ? data : new Uint8Array(data)));
  };
  const finish = () => {
    if (cancellation.cancelled) return;
    parser.push(decoder.finish());
    parser.finish();
    if (!terminal) fail(new Error("连接已结束，但未收到完整回复，请重试"));
  };

  // #ifdef H5
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const controller = typeof AbortController !== "undefined" ? new AbortController() : undefined;
  const unsubscribe = cancellation.onCancel(() => {
    controller?.abort();
    reader?.cancel().catch(() => {});
  });
  try {
    const response = await fetch(url, {
      method: "POST", headers, body: JSON.stringify(params), signal: controller?.signal,
    });
    if (cancellation.cancelled) return;
    if (!response.ok) throw new Error(`SSE connection failed: ${response.status}`);
    if (!response.body || typeof response.body.getReader !== "function") {
      feed(await response.text());
    } else {
      reader = response.body.getReader();
      while (!cancellation.cancelled && !terminal) {
        const { done, value } = await reader.read();
        if (done) break;
        feed(value);
      }
    }
    finish();
  } catch (error) {
    fail(error);
  } finally {
    unsubscribe();
    if (reader) {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
  // #endif

  // #ifndef H5
  // Mini-programs use uni's request task, not browser fetch/ReadableStream globals.
  await new Promise<void>((resolve) => {
    let task: UniApp.RequestTask | undefined;
    let receivedChunks = false;
    const unsubscribe = cancellation.onCancel(() => {
      task?.abort();
      resolve();
    });
    const close = () => { unsubscribe(); resolve(); };
    try {
      task = uni.request({
        url, method: "POST", header: headers, data: params,
        dataType: "text", enableChunkTransfer: true,
        success: (response) => {
          try {
            if (response.statusCode < 200 || response.statusCode >= 300) {
              throw new Error(`SSE connection failed: ${response.statusCode}`);
            }
            // Platforms without chunk callbacks can consume the same SSE request at EOF.
            if (!receivedChunks) feed(response.data as string);
            finish();
          } catch (error) { fail(error); }
          finally { close(); }
        },
        fail: (error) => { fail(new Error(error.errMsg || "网络连接失败")); close(); },
      });
      const chunkTask = task as UniApp.RequestTask & {
        onChunkReceived?: (callback: (response: { data: ArrayBuffer }) => void) => void;
      };
      chunkTask.onChunkReceived?.((response) => {
        if (cancellation.cancelled || terminal) return;
        receivedChunks = true;
        try { feed(response.data); }
        catch (error) { fail(error); task?.abort(); close(); }
      });
    } catch (error) { fail(error); close(); }
  });
  // #endif
}
