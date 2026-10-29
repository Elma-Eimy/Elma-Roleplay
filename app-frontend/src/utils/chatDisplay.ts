/**
 * 聊天展示层的纯函数：置底判定、入场动画筛选、最新回复定位与思考计时文案。
 * 只描述界面行为，不参与消息、候选或分支的业务判断。
 */

export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  viewportHeight: number;
}

/** 距底部小于该值时视为用户停留在底部，流式输出会自动跟随。 */
export const PINNED_BOTTOM_THRESHOLD = 120;

export function isNearBottom(
  metrics: ScrollMetrics,
  threshold = PINNED_BOTTOM_THRESHOLD
): boolean {
  // 视口高度未测得时无法判定，保持跟随以免首屏不置底。
  if (!(metrics.viewportHeight > 0)) return true;
  const distance = metrics.scrollHeight - metrics.scrollTop - metrics.viewportHeight;
  return distance <= threshold;
}

/**
 * 只有本地新产生的消息（乐观用户消息与流式占位）播放入场动画；
 * 历史、分页加载和以服务器数据重建的消息（`msg-` 前缀）直接显示，避免整屏重放。
 */
export function shouldAnimateMessageEntry(clientId?: string | null): boolean {
  if (!clientId) return false;
  return clientId.startsWith("user-") || clientId.startsWith("assistant-");
}

/** 返回最后一条 AI 消息的下标，不存在时为 -1。 */
export function findLatestAssistantIndex(
  messages: ReadonlyArray<{ role: string }>
): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") return index;
  }
  return -1;
}

/** 思考区标题；时长未知（如历史消息）时不展示秒数。 */
export function formatThoughtTitle(options: {
  isThinking: boolean;
  elapsedMs: number | null;
}): string {
  const seconds =
    options.elapsedMs === null ? null : Math.max(1, Math.round(options.elapsedMs / 1000));
  if (options.isThinking) {
    return seconds === null ? "思考中" : `思考中 · ${seconds}s`;
  }
  return seconds === null ? "已深度思考" : `已思考 ${seconds} 秒`;
}

/** 取思考文本最后一个非空行，用于折叠状态下的单行预览。 */
export function lastNonEmptyLine(text: string | null | undefined): string {
  if (!text) return "";
  const lines = String(text).split(/\r?\n/);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index].trim();
    if (line) return line;
  }
  return "";
}

export type ChatFontScale = "sm" | "md" | "lg" | "xl";
export type ChatLineSpacing = "compact" | "comfortable";
export type ChatBubbleStyle = "bubble" | "novel";
export type ChatColorTheme = "system" | "light" | "dark";

export interface ChatReadingPrefs {
  fontScale: ChatFontScale;
  lineSpacing: ChatLineSpacing;
  bubbleStyle: ChatBubbleStyle;
  colorTheme: ChatColorTheme;
}

export const DEFAULT_READING_PREFS: ChatReadingPrefs = {
  fontScale: "md",
  lineSpacing: "comfortable",
  bubbleStyle: "bubble",
  colorTheme: "system",
};

export const FONT_SCALE_OPTIONS: ReadonlyArray<{ value: ChatFontScale; label: string }> = [
  { value: "sm", label: "小" },
  { value: "md", label: "标准" },
  { value: "lg", label: "大" },
  { value: "xl", label: "特大" },
];

export const LINE_SPACING_OPTIONS: ReadonlyArray<{ value: ChatLineSpacing; label: string }> = [
  { value: "compact", label: "紧凑" },
  { value: "comfortable", label: "舒适" },
];

export const BUBBLE_STYLE_OPTIONS: ReadonlyArray<{ value: ChatBubbleStyle; label: string }> = [
  { value: "bubble", label: "气泡" },
  { value: "novel", label: "小说" },
];

export const COLOR_THEME_OPTIONS: ReadonlyArray<{ value: ChatColorTheme; label: string }> = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

export function normalizeReadingPrefs(raw: unknown): ChatReadingPrefs {
  const record = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const fontScale = FONT_SCALE_OPTIONS.some((item) => item.value === record.fontScale)
    ? (record.fontScale as ChatFontScale)
    : DEFAULT_READING_PREFS.fontScale;
  const lineSpacing = LINE_SPACING_OPTIONS.some((item) => item.value === record.lineSpacing)
    ? (record.lineSpacing as ChatLineSpacing)
    : DEFAULT_READING_PREFS.lineSpacing;
  const bubbleStyle = BUBBLE_STYLE_OPTIONS.some((item) => item.value === record.bubbleStyle)
    ? (record.bubbleStyle as ChatBubbleStyle)
    : DEFAULT_READING_PREFS.bubbleStyle;
  const colorTheme = COLOR_THEME_OPTIONS.some((item) => item.value === record.colorTheme)
    ? (record.colorTheme as ChatColorTheme)
    : DEFAULT_READING_PREFS.colorTheme;
  return { fontScale, lineSpacing, bubbleStyle, colorTheme };
}

/** 沉浸模式下根据滚动增量决定头部显隐；顶部附近始终显示。 */
export const HEADER_FADE_MIN_SCROLL_TOP = 80;
export const HEADER_FADE_DELTA = 18;

export function shouldFadeHeaderOnScroll(options: {
  currentHidden: boolean;
  scrollTop: number;
  previousScrollTop: number;
  isImmersive: boolean;
}): boolean {
  if (!options.isImmersive || options.scrollTop <= HEADER_FADE_MIN_SCROLL_TOP) return false;
  const delta = options.scrollTop - options.previousScrollTop;
  if (delta >= HEADER_FADE_DELTA) return true;
  if (delta <= -HEADER_FADE_DELTA) return false;
  return options.currentHidden;
}

/** 相邻消息间隔达到 30 分钟时展示一条时间分隔线。 */
export const TIME_DIVIDER_GAP_MS = 30 * 60 * 1000;

const padTwo = (value: number): string => (value < 10 ? `0${value}` : String(value));

const startOfLocalDay = (date: Date): number =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

export function formatMessageTimestamp(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "";
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  const date = new Date(time);
  const hhmm = `${padTwo(date.getHours())}:${padTwo(date.getMinutes())}`;
  const dayDiff = Math.round((startOfLocalDay(now) - startOfLocalDay(date)) / 86400000);
  if (dayDiff === 0) return hhmm;
  if (dayDiff === 1) return `昨天 ${hhmm}`;
  const monthDay = `${padTwo(date.getMonth() + 1)}-${padTwo(date.getDate())} ${hhmm}`;
  if (date.getFullYear() === now.getFullYear()) return monthDay;
  return `${date.getFullYear()}-${monthDay}`;
}

export function computeTimeDividers(
  messages: ReadonlyArray<{ created_at?: string | null }>,
  options: { gapMs?: number; now?: Date } = {}
): Array<string | null> {
  const gapMs = options.gapMs ?? TIME_DIVIDER_GAP_MS;
  const now = options.now ?? new Date();
  const dividers: Array<string | null> = new Array(messages.length).fill(null);
  let previousTime: number | null = null;
  for (let index = 0; index < messages.length; index += 1) {
    const raw = messages[index]?.created_at;
    const parsed = raw ? Date.parse(raw) : Number.NaN;
    if (!Number.isFinite(parsed)) continue;
    if (previousTime !== null && parsed - previousTime >= gapMs) {
      dividers[index] = formatMessageTimestamp(raw, now) || null;
    }
    previousTime = parsed;
  }
  return dividers;
}

/** 长会话默认只挂载末尾 80 条消息，向上滚动时按步长补挂已加载的更早消息。 */
export const INITIAL_RENDER_WINDOW = 80;
export const RENDER_WINDOW_STEP = 40;

export interface RenderWindowSlice {
  startIndex: number;
  hiddenCount: number;
}

export function computeRenderWindow(total: number, windowSize: number): RenderWindowSlice {
  const safeTotal = Math.max(0, total);
  const safeWindow = Math.max(1, windowSize);
  const startIndex = Math.max(0, safeTotal - safeWindow);
  return {
    startIndex,
    hiddenCount: startIndex,
  };
}

/** 有界 LRU 缓存，用于复用已完成消息的 Markdown 渲染结果。 */
export function createBoundedCache<V>(maxEntries = 200) {
  const limit = Math.max(1, maxEntries);
  const map = new Map<string, V>();
  return {
    get(key: string): V | undefined {
      if (!map.has(key)) return undefined;
      const value = map.get(key)!;
      map.delete(key);
      map.set(key, value);
      return value;
    },
    set(key: string, value: V): void {
      if (map.has(key)) map.delete(key);
      map.set(key, value);
      if (map.size > limit) {
        const oldest = map.keys().next().value;
        if (oldest !== undefined) map.delete(oldest);
      }
    },
    get size(): number {
      return map.size;
    },
    clear(): void {
      map.clear();
    },
  };
}
