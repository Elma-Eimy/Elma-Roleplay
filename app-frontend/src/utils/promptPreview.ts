export interface CompiledPromptMessage {
  role: string;
  content: string;
}

export type PromptSectionKey =
  | "system_core"
  | "lorebook"
  | "examples"
  | "context_summary"
  | "history"
  | "dynamic_context"
  | "current_input"
  | "post_history";

export interface PromptPreviewItem {
  role: string;
  content: string;
  label?: string;
}

export interface PromptPreviewSection {
  key: PromptSectionKey;
  title: string;
  description: string;
  items: PromptPreviewItem[];
  totalChars: number;
  emptyHint?: string;
}

const EXAMPLE_CONTEXT_MARKER = "【对话示例说明】";
const EXAMPLE_END_MARKER = "【对话示例结束】";
const CONTEXT_SUMMARY_MARKER = "【较早对话的压缩摘要】";
const DYNAMIC_CONTEXT_HEADER = "【当前回合动态背景】";
const LEGACY_DYNAMIC_HEADER =
  "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】";
const CURRENT_USER_MARKER = "【当前用户的最新消息：】";
const GROUP_VISIBLE_HISTORY_MARKER = "【其他成员的可见历史资料】";

const LOREBOOK_TAG_SOURCE = "<lorebook_knowledge\\b([^>]*)>[\\s\\S]*?<\\/lorebook_knowledge>";
const HAS_LOREBOOK_TAG_RE = new RegExp(LOREBOOK_TAG_SOURCE, "i");
const GENERATED_LOREBOOK_RE = /<lorebook_knowledge\s+position=/i;

const DYNAMIC_TAG_LABELS: Record<string, string> = {
  current_scenario: "当前场景",
  current_role_state: "当前角色状态",
  cognition_state: "认知状态",
  current_status: "心情与好感度",
  ongoing_events: "进行中事件",
  pending_memories: "待整理记忆",
  recalled_memories: "长期记忆召回",
  factual_relationships: "知识图谱关系",
  context_summary: "较早对话摘要",
};

const SYSTEM_HEADER_LABELS: Record<string, string> = {
  "【核心扮演指令】": "核心扮演指令",
  "【角色设定】": "角色设定",
  "【性格特点】": "性格特点",
  "【对话示例说明】": "对话示例说明",
  "【未结构化对话示例】": "未结构化对话示例",
  "【重要：输出格式要求】": "输出格式要求",
  "【状态增量协议】": "状态增量协议",
  "【群聊输出约束】": "群聊输出约束",
};

const GROUP_HEADER_LABELS: Record<string, string> = {
  "【群聊身份与共同起点】": "群聊身份与共同起点",
  "【全员可见的冻结开场】": "全员可见开场",
  "【本人在群聊中形成的认识】": "成员主观认识",
  "【本人相关记忆】": "成员相关记忆",
  "【本人入群前的相关记忆】": "入群前继承记忆",
  "【个人可见历史顺序】": "个人可见历史顺序",
  "【用户的待执行安排】": "待执行安排",
  "【本次承接依据】": "本次承接依据",
  "【本次主要回应对象】": "主要回应对象",
  "【本次发言依据】": "本次发言依据",
};

function splitByKnownHeaders(
  text: string,
  role: string,
  headerLabels: Record<string, string>,
  fallbackLabel: string
): PromptPreviewItem[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  const escapedHeaders = Object.keys(headerLabels).map((header) =>
    header.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  if (escapedHeaders.length === 0) {
    return [{ role, content: trimmed, label: fallbackLabel }];
  }

  const headerRegex = new RegExp(`(^|\\n\\n)(${escapedHeaders.join("|")})`, "g");
  const matches: Array<{ index: number; header: string; startOffset: number }> = [];
  let match: RegExpExecArray | null;
  while ((match = headerRegex.exec(trimmed)) !== null) {
    matches.push({
      index: match.index + match[1].length,
      header: match[2],
      startOffset: match.index,
    });
  }

  if (matches.length === 0) {
    return [{ role, content: trimmed, label: fallbackLabel }];
  }

  const items: PromptPreviewItem[] = [];
  if (matches[0].index > 0) {
    const prefix = trimmed.slice(0, matches[0].index).trim();
    if (prefix) {
      items.push({ role, content: prefix, label: fallbackLabel });
    }
  }

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index;
    const end = i + 1 < matches.length ? matches[i + 1].startOffset : trimmed.length;
    const slice = trimmed.slice(start, end).trim();
    if (slice) {
      items.push({
        role,
        content: slice,
        label: headerLabels[matches[i].header] || fallbackLabel,
      });
    }
  }

  return items;
}

function formatLorebookLabel(attrs: string): string {
  const posMatch = attrs.match(/position=["']([^"']+)["']/i);
  const depthMatch = attrs.match(/depth=["']([^"']+)["']/i);
  if (posMatch && depthMatch) {
    return `世界书 · ${posMatch[1]} (depth=${depthMatch[1]})`;
  }
  if (posMatch) {
    return `世界书 · ${posMatch[1]}`;
  }
  return "世界书条目";
}

function extractLorebookBlocks(
  text: string,
  role: string
): { lorebookItems: PromptPreviewItem[]; remainder: string } {
  const lorebookItems: PromptPreviewItem[] = [];
  let cursor = 0;
  let remainder = "";

  const regex = new RegExp(LOREBOOK_TAG_SOURCE, "gi");
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    remainder += text.slice(cursor, match.index);
    lorebookItems.push({
      role,
      content: match[0].trim(),
      label: formatLorebookLabel(match[1] || ""),
    });
    cursor = match.index + match[0].length;
  }
  remainder += text.slice(cursor);

  return {
    lorebookItems,
    remainder: remainder.trim(),
  };
}

function parseDynamicContextContent(
  rawContent: string,
  role: string,
  lorebookTarget: PromptPreviewItem[],
  dynamicTarget: PromptPreviewItem[]
): void {
  let body = rawContent.trim();
  if (body.startsWith(DYNAMIC_CONTEXT_HEADER)) {
    body = body.slice(DYNAMIC_CONTEXT_HEADER.length).trim();
  } else if (body.startsWith(LEGACY_DYNAMIC_HEADER)) {
    body = body.slice(LEGACY_DYNAMIC_HEADER.length).trim();
  }
  if (!body) return;

  const { lorebookItems, remainder } = extractLorebookBlocks(body, role);
  lorebookTarget.push(...lorebookItems);
  if (!remainder) return;

  const tagNames = Object.keys(DYNAMIC_TAG_LABELS).join("|");
  const tagRegex = new RegExp(
    `<(${tagNames})(?:\\s[^>]*)?>[\\s\\S]*?<\\/\\1>(?:\\n[^\\n<【]+)?`,
    "g"
  );

  const chunks: Array<{ start: number; end: number; item: PromptPreviewItem }> = [];
  let match: RegExpExecArray | null;
  while ((match = tagRegex.exec(remainder)) !== null) {
    chunks.push({
      start: match.index,
      end: match.index + match[0].length,
      item: {
        role,
        content: match[0].trim(),
        label: DYNAMIC_TAG_LABELS[match[1]] || match[1],
      },
    });
  }

  let cursor = 0;
  for (const chunk of chunks) {
    if (chunk.start > cursor) {
      const prefix = remainder.slice(cursor, chunk.start).trim();
      if (prefix) {
        dynamicTarget.push(
          ...splitByKnownHeaders(prefix, role, GROUP_HEADER_LABELS, "动态背景")
        );
      }
    }
    dynamicTarget.push(chunk.item);
    cursor = chunk.end;
  }

  if (cursor < remainder.length) {
    const tail = remainder.slice(cursor).trim();
    if (tail) {
      dynamicTarget.push(
        ...splitByKnownHeaders(tail, role, GROUP_HEADER_LABELS, "动态背景")
      );
    }
  }
}

function isPostHistoryMessage(message: CompiledPromptMessage): boolean {
  if (message.role !== "system") return false;
  const content = (message.content || "").trim();
  if (
    content.startsWith(EXAMPLE_END_MARKER) ||
    content.startsWith(CONTEXT_SUMMARY_MARKER) ||
    content.startsWith(DYNAMIC_CONTEXT_HEADER) ||
    content.startsWith(GROUP_VISIBLE_HISTORY_MARKER)
  ) {
    return false;
  }
  const stripped = content.replace(new RegExp(LOREBOOK_TAG_SOURCE, "gi"), "").trim();
  return stripped.length > 0;
}

export function buildPromptPreviewSections(
  messages: CompiledPromptMessage[] | null | undefined
): PromptPreviewSection[] {
  const payload = messages || [];
  if (payload.length === 0) return [];

  const buckets: Record<PromptSectionKey, PromptPreviewItem[]> = {
    system_core: [],
    lorebook: [],
    examples: [],
    context_summary: [],
    history: [],
    dynamic_context: [],
    current_input: [],
    post_history: [],
  };

  const hasPostHistory =
    payload.length > 1 && isPostHistoryMessage(payload[payload.length - 1]);
  const conversationEnd = hasPostHistory ? payload.length - 1 : payload.length;

  let exampleEndIndex: number | null = null;
  for (let i = 1; i < conversationEnd; i++) {
    const msg = payload[i];
    if (
      msg.role === "system" &&
      (msg.content || "").trim().startsWith(EXAMPLE_END_MARKER)
    ) {
      exampleEndIndex = i;
      break;
    }
  }

  const userSearchFloor = exampleEndIndex !== null ? exampleEndIndex : 0;
  let finalUserIndex: number | null = null;
  for (let i = conversationEnd - 1; i > userSearchFloor; i--) {
    const msg = payload[i];
    if (msg.role === "user" && !GENERATED_LOREBOOK_RE.test(msg.content || "")) {
      finalUserIndex = i;
      break;
    }
  }

  // 1. 首条 system 消息（核心指令 + 人设 + 可选未结构化示例/示例说明）
  const firstContent = payload[0].content || "";
  const exampleMarkerIndex = firstContent.indexOf(EXAMPLE_CONTEXT_MARKER);
  if (exampleMarkerIndex >= 0) {
    const corePart = firstContent.slice(0, exampleMarkerIndex).trim();
    const examplePart = firstContent.slice(exampleMarkerIndex).trim();
    buckets.system_core.push(
      ...splitByKnownHeaders(corePart, payload[0].role, SYSTEM_HEADER_LABELS, "系统提示")
    );
    buckets.examples.push(
      ...splitByKnownHeaders(examplePart, payload[0].role, SYSTEM_HEADER_LABELS, "示例说明")
    );
  } else {
    buckets.system_core.push(
      ...splitByKnownHeaders(firstContent, payload[0].role, SYSTEM_HEADER_LABELS, "系统提示")
    );
  }

  // 2. 紧跟在首条之后的静态前置 system 消息（before_char / after_char / character_definition）
  const leadingSystemIndexes = new Set<number>();
  for (let i = 1; i < conversationEnd; i++) {
    const msg = payload[i];
    if (msg.role !== "system") break;
    const content = (msg.content || "").trim();
    if (
      content.startsWith(CONTEXT_SUMMARY_MARKER) ||
      content.startsWith(DYNAMIC_CONTEXT_HEADER) ||
      content.startsWith(LEGACY_DYNAMIC_HEADER) ||
      content.startsWith(GROUP_VISIBLE_HISTORY_MARKER)
    ) {
      break;
    }
    leadingSystemIndexes.add(i);
    if (HAS_LOREBOOK_TAG_RE.test(content)) {
      const { lorebookItems, remainder } = extractLorebookBlocks(content, msg.role);
      buckets.lorebook.push(...lorebookItems);
      if (remainder) {
        buckets.system_core.push(
          ...splitByKnownHeaders(remainder, msg.role, SYSTEM_HEADER_LABELS, "角色补充")
        );
      }
    } else if (content.startsWith(EXAMPLE_END_MARKER)) {
      buckets.examples.push({ role: msg.role, content, label: "示例结束边界" });
    } else {
      buckets.system_core.push(
        ...splitByKnownHeaders(content, msg.role, SYSTEM_HEADER_LABELS, "角色设定")
      );
    }
  }

  // 3. 示例区、历史消息、深度世界书、动态背景与本轮用户输入
  for (let i = 1; i < conversationEnd; i++) {
    if (leadingSystemIndexes.has(i)) continue;
    const msg = payload[i];
    const content = (msg.content || "").trim();

    if (exampleEndIndex !== null && i <= exampleEndIndex) {
      if (i === exampleEndIndex) {
        buckets.examples.push({ role: msg.role, content, label: "示例结束边界" });
      } else if (HAS_LOREBOOK_TAG_RE.test(content)) {
        const { lorebookItems, remainder } = extractLorebookBlocks(content, msg.role);
        buckets.lorebook.push(...lorebookItems);
        if (remainder) {
          buckets.examples.push({ role: msg.role, content: remainder, label: "对话示例" });
        }
      } else {
        buckets.examples.push({ role: msg.role, content, label: "对话示例" });
      }
      continue;
    }

    if (i === finalUserIndex) {
      const markerIdx = content.indexOf(CURRENT_USER_MARKER);
      if (markerIdx >= 0) {
        const contextPart = content.slice(0, markerIdx).trim();
        const userPart = content.slice(markerIdx + CURRENT_USER_MARKER.length).trim();
        if (contextPart) {
          parseDynamicContextContent(
            contextPart,
            "system",
            buckets.lorebook,
            buckets.dynamic_context
          );
        }
        buckets.current_input.push({
          role: msg.role,
          content: userPart || content,
          label: "本轮输入",
        });
      } else {
        buckets.current_input.push({
          role: msg.role,
          content,
          label: "本轮输入",
        });
      }
      continue;
    }

    if (msg.role === "system" && content.startsWith(CONTEXT_SUMMARY_MARKER)) {
      buckets.context_summary.push({ role: msg.role, content, label: "对话压缩摘要" });
    } else if (
      msg.role === "system" &&
      (content.startsWith(DYNAMIC_CONTEXT_HEADER) || content.startsWith(LEGACY_DYNAMIC_HEADER))
    ) {
      parseDynamicContextContent(
        content,
        msg.role,
        buckets.lorebook,
        buckets.dynamic_context
      );
    } else if (HAS_LOREBOOK_TAG_RE.test(content)) {
      const { lorebookItems, remainder } = extractLorebookBlocks(content, msg.role);
      buckets.lorebook.push(...lorebookItems);
      if (remainder) {
        buckets.history.push({ role: msg.role, content: remainder, label: "对话记录" });
      }
    } else if (msg.role === "system" && content.startsWith(GROUP_VISIBLE_HISTORY_MARKER)) {
      buckets.history.push({ role: msg.role, content, label: "群聊成员历史" });
    } else {
      buckets.history.push({
        role: msg.role,
        content,
        label: msg.role === "system" ? "角色深度提示" : "对话记录",
      });
    }
  }

  // 4. 末尾 PHI 与输出格式契约
  if (hasPostHistory) {
    const phiMsg = payload[payload.length - 1];
    buckets.post_history.push(
      ...splitByKnownHeaders(
        phiMsg.content || "",
        phiMsg.role,
        SYSTEM_HEADER_LABELS,
        "后置角色指令 (PHI)"
      )
    );
  }

  const specs: Array<{
    key: PromptSectionKey;
    title: string;
    description: string;
    keepWhenEmpty?: boolean;
    emptyHint?: string;
  }> = [
    {
      key: "system_core",
      title: "核心指令与角色设定",
      description: "主扮演指令、角色描述与性格",
    },
    {
      key: "lorebook",
      title: "世界书激活 (Lorebook)",
      description: "静态位置与本轮触发的世界书条目",
    },
    {
      key: "examples",
      title: "对话示例 (mes_example)",
      description: "角色卡 few-shot 示例与风格说明",
      keepWhenEmpty: true,
      emptyHint:
        "本轮未单独注入对话示例（可能因角色卡未填写、模板已通过 {{mesExamples}} 宏内联，或子分支沿用父分支历史）。",
    },
    {
      key: "context_summary",
      title: "较早对话摘要",
      description: "历史压缩摘要",
    },
    {
      key: "history",
      title: "近期对话历史",
      description: "传入模型的上下文轮次与群聊可见记录",
    },
    {
      key: "dynamic_context",
      title: "当前回合动态背景",
      description: "场景、状态、认知、记忆与图谱等实时上下文",
    },
    {
      key: "current_input",
      title: "当前用户输入",
      description: "本轮触发组装的用户最新消息",
    },
    {
      key: "post_history",
      title: "后置指令与输出格式 (PHI)",
      description: "角色卡后置提示、状态增量协议与 XML 格式要求",
    },
  ];

  const result: PromptPreviewSection[] = [];
  for (const spec of specs) {
    const items = buckets[spec.key];
    if (items.length === 0 && !spec.keepWhenEmpty) continue;
    const totalChars = items.reduce((sum, item) => sum + item.content.length, 0);
    result.push({
      key: spec.key,
      title: spec.title,
      description: spec.description,
      items,
      totalChars,
      ...(items.length === 0 && spec.emptyHint ? { emptyHint: spec.emptyHint } : {}),
    });
  }

  return result;
}
