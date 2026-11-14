const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { parse, compileTemplate } = require("@vue/compiler-sfc");
const vue = require("vue");
const { createLoader, sourceRoot } = require("./helpers/load-ts.cjs");

const filename = path.join(sourceRoot, "components/chat/ChatComposer.vue");
const { descriptor } = parse(fs.readFileSync(filename, "utf8"));
const compiled = compileTemplate({ source: descriptor.template.content, filename, id: "composer-test" });
assert.deepEqual(compiled.errors, []);
const code = compiled.code
  .replace(/import \{([\s\S]*?)\} from "vue"/, (_, names) => `const {${names.replace(/ as /g, ": ")}} = vue;`)
  .replace("export function render", "function render");
const render = vm.runInNewContext(`${code}\nrender`, { vue });

function find(node, className) {
  if (!node || typeof node !== "object") return null;
  if (String(node.props?.class || "").split(" ").includes(className)) return node;
  for (const child of Array.isArray(node.children) ? node.children : []) {
    const match = find(child, className);
    if (match) return match;
  }
  return null;
}

test("composer blocks both send gestures while disabled or generating and honors group input limits", () => {
  for (const [disabled, isGenerating] of [[true, false], [false, true], [false, false]]) {
    const events = [];
    const tree = render({ modelValue: "draft", disabled, isGenerating, maxlength: 20000,
      showModelSettings: false, isAndroid: false, isFocused: false, wrapperStyle: {},
      keyboardHeight: 0, placeholderText: "", emit: event => events.push(event), handleInput() {},
    }, []);
    const input = find(tree, "chat-input"), send = find(tree, "send-btn");
    assert.equal(input.props.maxlength, 20000);
    assert.equal(input.props.disabled, disabled);
    input.props.onConfirm();
    send.props.onTap();
    assert.equal(events.length, disabled || isGenerating ? 0 : 2);
    assert.equal(find(tree, "reasoning-toggle-row"), null);
  }
});

test("shared chat markdown retains dialogue and state formatting while escaping raw HTML", () => {
  const markdown = createLoader({ mocks: { "markdown-it": { default: require("markdown-it") } } })("utils/markdown.ts");
  const html = markdown.renderChatMarkdown('**你好**\n“欢迎回来”\n<script>alert(1)</script>\n\n```state\n心情：开心\n```');
  assert.match(html, /class="md-strong"/);
  assert.match(html, /class="md-dialogue"/);
  assert.match(html, /class="md-status-card"/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});
