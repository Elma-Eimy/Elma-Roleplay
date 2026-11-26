/**
 * 气泡文本清洗、占位符替换与 <thought> 思考内容解析工具。
 */

export function replaceBubblePlaceholders(
  text: string,
  characterName?: string,
  userNickname?: string
): string {
  if (!text) return "";
  const str = String(text);
  const charName = characterName || "角色";
  const userName = userNickname || "用户";
  return str
    .replace(/\{\{char\}\}/gi, charName)
    .replace(/\{\{user\}\}/gi, userName);
}

export function stripStatusTags(text: string): string {
  return text.replace(/<status[^>]*\/?>/gi, "");
}

export function stripThoughtTags(text: string): string {
  return text.replace(/<\/?thought[^>]*>/gi, "");
}

export function parseBubbleContent(options: {
  content: unknown;
  reasoningContent?: unknown;
  isUser: boolean;
  characterName?: string;
  userNickname?: string;
}): { thought: string; reply: string } {
  const rawContent =
    options.content === null || options.content === undefined ? "" : String(options.content);

  // 过滤掉 <status ...> 自定义标签，防止 rich-text 渲染自定义 XML 标签导致原生端崩溃
  const cleaned = replaceBubblePlaceholders(
    stripStatusTags(rawContent),
    options.characterName,
    options.userNickname
  );

  if (options.isUser) {
    return { thought: "", reply: cleaned };
  }

  // 优先采用独立的 reasoning_content 字段（API 标准格式）
  let thought = options.reasoningContent ? String(options.reasoningContent) : "";
  let reply = cleaned;

  // 若独立字段为空，再回退解析 <thought> 标签
  if (!thought) {
    const thoughtRegex = /<thought>([\s\S]*?)<\/thought>/i;
    const match = cleaned.match(thoughtRegex);
    if (match) {
      thought = match[1].trim();
      reply = cleaned.replace(thoughtRegex, "").trim();
    }
  } else {
    reply = stripThoughtTags(reply);
  }

  thought = replaceBubblePlaceholders(thought, options.characterName, options.userNickname);

  return {
    thought: stripThoughtTags(thought),
    reply: stripThoughtTags(reply),
  };
}
