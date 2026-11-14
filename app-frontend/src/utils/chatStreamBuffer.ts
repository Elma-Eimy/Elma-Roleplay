type ChunkConsumer = (tempId: string, text: string) => void;

/** 合并高频分块；消息归属与请求是否有效由调用方判断。 */
export function createChatStreamBuffer(onText: ChunkConsumer, onReasoning: ChunkConsumer) {
  const pendingText = new Map<string, string>();
  const pendingReasoning = new Map<string, string>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  function cancelTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function flush() {
    cancelTimer();
    pendingText.forEach((text, tempId) => onText(tempId, text));
    pendingReasoning.forEach((text, tempId) => onReasoning(tempId, text));
    pendingText.clear();
    pendingReasoning.clear();
  }

  function append(pending: Map<string, string>, tempId: string, chunk: string) {
    if (!chunk) return;
    pending.set(tempId, `${pending.get(tempId) || ""}${chunk}`);
    if (timer === null) timer = setTimeout(flush, 48);
  }

  function clear() {
    cancelTimer();
    pendingText.clear();
    pendingReasoning.clear();
  }

  return {
    appendText: (tempId: string, chunk: string) => append(pendingText, tempId, chunk),
    appendReasoning: (tempId: string, chunk: string) => append(pendingReasoning, tempId, chunk),
    flush,
    clear,
  };
}
