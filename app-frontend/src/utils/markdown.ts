const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

/**
 * Render every fenced section as role-play state data. The fence info string
 * is deliberately ignored because character-card authors use arbitrary tags.
 */
export const renderRoleplayStateBlock = (content: string): string => {
  const lines = content.replace(/(?:\r?\n)$/, "").split(/\r?\n/);
  const renderedLines = lines
    .map((rawLine) => {
      const line = rawLine.trim();
      if (!line) return '<div class="md-status-spacer"></div>';

      const fieldMatch = line.match(/^(.{1,24}?)[：:]\s*(.*)$/);
      if (fieldMatch) {
        return [
          '<div class="md-status-row">',
          `<span class="md-status-key">${escapeHtml(fieldMatch[1].trim())}</span>`,
          `<span class="md-status-value">${escapeHtml(fieldMatch[2])}</span>`,
          "</div>",
        ].join("");
      }

      return `<div class="md-status-line">${escapeHtml(line)}</div>`;
    })
    .join("");

  return [
    '<div class="md-status-card">',
    '<div class="md-status-header">',
    '<span class="md-status-dot"></span>',
    '<span class="md-status-title">角色状态</span>',
    "</div>",
    `<div class="md-status-body">${renderedLines}</div>`,
    "</div>",
  ].join("");
};
