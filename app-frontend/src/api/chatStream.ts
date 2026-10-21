import { createCancellation } from "../utils/cancellation";
import type { Cancellation } from "../utils/cancellation";
import { createUtf8Decoder } from "../utils/sse";
import { createChatStreamProtocol } from "../utils/chatStreamProtocol";
import type { StreamCallbacks } from "../utils/chatStreamProtocol";
import type { ChatRequest } from "./chat";

export async function receiveChatStream(
  url: string,
  headers: Record<string, string>,
  params: ChatRequest,
  callbacks: StreamCallbacks,
  cancellation: Cancellation = createCancellation()
): Promise<void> {
  if (cancellation.cancelled) return;
  const protocol = createChatStreamProtocol(callbacks, () => cancellation.cancelled);
  const fail = protocol.fail;
  const decoder = createUtf8Decoder();
  const feed = (data: string | ArrayBuffer | Uint8Array) => {
    if (protocol.finished || cancellation.cancelled) return;
    protocol.push(typeof data === "string" ? data : decoder.push(data instanceof Uint8Array ? data : new Uint8Array(data)));
  };
  const finish = () => {
    if (cancellation.cancelled) return;
    protocol.push(decoder.finish());
    protocol.finish();
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
      while (!cancellation.cancelled && !protocol.finished) {
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
        if (cancellation.cancelled || protocol.finished) return;
        receivedChunks = true;
        try { feed(response.data); }
        catch (error) { fail(error); task?.abort(); close(); }
      });
    } catch (error) { fail(error); close(); }
  });
  // #endif
}
