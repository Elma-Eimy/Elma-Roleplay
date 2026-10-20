/** A decoder belongs to one stream; incomplete UTF-8 bytes survive chunk boundaries. */
export function createUtf8Decoder() {
  const native = typeof TextDecoder !== "undefined" ? new TextDecoder("utf-8") : null;
  let pending: number[] = [];
  const decode = (chunk: Uint8Array, final = false): string => {
    if (native) return native.decode(chunk, { stream: !final });
    const bytes = pending.concat(Array.from(chunk));
    pending = [];
    let output = "";
    for (let i = 0; i < bytes.length;) {
      const first = bytes[i];
      if (first < 0x80) { output += String.fromCharCode(first); i++; continue; }
      const length = first >= 0xc2 && first <= 0xdf ? 2
        : first >= 0xe0 && first <= 0xef ? 3
        : first >= 0xf0 && first <= 0xf4 ? 4 : 0;
      if (!length) { output += "\ufffd"; i++; continue; }
      if (i + length > bytes.length) {
        if (final) output += "\ufffd";
        else pending = bytes.slice(i);
        break;
      }
      let point = first & (0x7f >> length);
      let valid = true;
      for (let j = 1; j < length; j++) {
        if ((bytes[i + j] & 0xc0) !== 0x80) { valid = false; break; }
        point = (point << 6) | (bytes[i + j] & 0x3f);
      }
      if (!valid || point < (length === 2 ? 0x80 : length === 3 ? 0x800 : 0x10000)
        || point > 0x10ffff || (point >= 0xd800 && point <= 0xdfff)) {
        output += "\ufffd"; i++; continue;
      }
      output += String.fromCodePoint(point);
      i += length;
    }
    return output;
  };
  return { push: (chunk: Uint8Array) => decode(chunk), finish: () => decode(new Uint8Array(), true) };
}

/** Parse SSE frames independently of the network transport and line boundaries. */
export function createSSEParser(onData: (data: string) => void) {
  let buffer = "";
  let data: string[] = [];
  const dispatch = () => {
    if (!data.length) return;
    const payload = data.join("\n");
    data = [];
    onData(payload);
  };
  const line = (value: string) => {
    if (!value) dispatch();
    else if (value.startsWith("data:")) {
      const valuePart = value.slice(5);
      data.push(valuePart.startsWith(" ") ? valuePart.slice(1) : valuePart);
    }
  };
  const push = (text: string) => {
    buffer += text;
    while (true) {
      const end = buffer.search(/[\r\n]/);
      if (end < 0 || (buffer[end] === "\r" && end === buffer.length - 1)) break;
      const value = buffer.slice(0, end);
      const width = buffer[end] === "\r" && buffer[end + 1] === "\n" ? 2 : 1;
      buffer = buffer.slice(end + width);
      line(value);
    }
  };
  return {
    push,
    finish() {
      if (buffer.endsWith("\r")) push("\n");
      if (buffer) line(buffer);
      buffer = "";
      dispatch();
    },
  };
}
