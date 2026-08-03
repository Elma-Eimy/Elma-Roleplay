/**
 * Some character cards instruct the model to wrap its entire conversational
 * reply in an unlabelled Markdown fence. Treat that outer fence as transport
 * formatting, while leaving labelled and inline code blocks untouched.
 */
export const unwrapWholeMessageFence = (
  content: string,
  allowUnclosedFence = false
): string => {
  const opening = content.match(
    /^[\t ]*(?:\r?\n[\t ]*)*(`{3,})[\t ]*(?:\r?\n|$)/
  );

  if (!opening) return content;

  const fence = opening[1];
  const body = content.slice(opening[0].length);
  const closing = new RegExp(
    `(?:\\r?\\n)?[\\t ]*${fence}[\\t ]*(?:\\r?\\n[\\t ]*)*$`
  );
  const closingMatch = closing.exec(body);

  if (closingMatch) {
    return body.slice(0, closingMatch.index);
  }

  return allowUnclosedFence ? body : content;
};
