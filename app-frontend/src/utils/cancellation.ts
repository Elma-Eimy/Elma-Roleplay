/** Cancellation shared by browser streams, uni request tasks and mock timers. */
export function createCancellation() {
  let cancelled = false;
  const listeners = new Set<() => void>();
  return {
    get cancelled() { return cancelled; },
    cancel() {
      if (cancelled) return;
      cancelled = true;
      const callbacks = [...listeners];
      listeners.clear();
      callbacks.forEach((callback) => callback());
    },
    onCancel(callback: () => void) {
      if (cancelled) callback();
      else listeners.add(callback);
      return () => { listeners.delete(callback); };
    },
  };
}

export type Cancellation = ReturnType<typeof createCancellation>;
