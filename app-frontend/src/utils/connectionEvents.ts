/** 连接地址持久化成功后，同步使旧服务器的内存状态失效。 */
const serverChangeListeners = new Set<() => void>();

export function onServerChange(listener: () => void) {
  serverChangeListeners.add(listener);
  return () => { serverChangeListeners.delete(listener); };
}

export function notifyServerChange() {
  for (const listener of [...serverChangeListeners]) listener();
}
