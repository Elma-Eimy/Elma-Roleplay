const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoader } = require("./helpers/load-ts.cjs");

const { buildPromptPreviewSections } = createLoader()("utils/promptPreview.ts");

test("groups single-chat prompt with mes_example, lorebook, summary, history, dynamic tags and PHI", () => {
  const messages = [
    {
      role: "system",
      content: [
        "【核心扮演指令】\n保持角色口吻。",
        "【角色设定】\n调查员林雾。",
        "【性格特点】\n冷静敏锐。",
        "【对话示例说明】\n以下示例仅用于参考。",
        "【未结构化对话示例】\n林雾推了推眼镜，没有立刻接话。",
      ].join("\n\n"),
    },
    {
      role: "system",
      content: '<lorebook_knowledge position="before_char">\n城市设定\n</lorebook_knowledge>',
    },
    { role: "user", content: "示例提问" },
    { role: "assistant", content: "<reply>示例回答</reply>" },
    { role: "system", content: "【对话示例结束】\n以上仅为风格示例。" },
    {
      role: "system",
      content: '【较早对话的压缩摘要】\n<context_summary>\n{"summary":"之前查过档案"}\n</context_summary>',
    },
    { role: "user", content: "真实历史提问" },
    { role: "assistant", content: "<reply>真实历史回答</reply>" },
    {
      role: "system",
      content: [
        "【当前回合动态背景】",
        "<lorebook_knowledge position=\"top_an\">\n作者顶注\n</lorebook_knowledge>",
        "<current_scenario>\n雨夜事务所\n</current_scenario>",
        "<cognition_state>\n怀疑线人\n</cognition_state>",
        "<current_status>\n心情: 警惕\n</current_status>",
        "<recalled_memories>\n- 记忆片段\n</recalled_memories>",
        "<factual_relationships>\n线人 -> 隐瞒证据\n</factual_relationships>",
      ].join("\n\n"),
    },
    { role: "user", content: "我们现在出发吗？" },
    {
      role: "system",
      content: '<lorebook_knowledge position="at_depth" depth="0">\n补充细节\n</lorebook_knowledge>',
    },
    {
      role: "system",
      content: "角色后置指令\n\n【重要：输出格式要求】\n<reply>...</reply>",
    },
  ];

  const sections = buildPromptPreviewSections(messages);
  const byKey = Object.fromEntries(sections.map((section) => [section.key, section]));

  assert.equal(byKey.system_core.items.length, 3);
  assert.deepEqual(
    Array.from(byKey.system_core.items, (item) => item.label),
    ["核心扮演指令", "角色设定", "性格特点"]
  );

  assert.equal(byKey.lorebook.items.length, 3);
  assert.match(byKey.lorebook.items[0].label, /before_char/);
  assert.match(byKey.lorebook.items[1].label, /top_an/);
  assert.match(byKey.lorebook.items[2].label, /at_depth.*depth=0/);

  assert.equal(byKey.examples.items.length, 5);
  assert.equal(byKey.examples.items[0].label, "对话示例说明");
  assert.equal(byKey.examples.items[1].label, "未结构化对话示例");
  assert.equal(byKey.examples.items[2].role, "user");
  assert.equal(byKey.examples.items[3].role, "assistant");
  assert.equal(byKey.examples.items[4].label, "示例结束边界");

  assert.equal(byKey.context_summary.items.length, 1);
  assert.equal(byKey.history.items.length, 2);

  assert.equal(byKey.dynamic_context.items.length, 5);
  assert.deepEqual(
    Array.from(byKey.dynamic_context.items, (item) => item.label),
    ["当前场景", "认知状态", "心情与好感度", "长期记忆召回", "知识图谱关系"]
  );

  assert.equal(byKey.current_input.items.length, 1);
  assert.equal(byKey.current_input.items[0].content, "我们现在出发吗？");

  assert.equal(byKey.post_history.items.length, 2);
  assert.equal(byKey.post_history.items[1].label, "输出格式要求");
});

test("keeps examples section visible with hint when no standalone examples are injected", () => {
  const sections = buildPromptPreviewSections([
    { role: "system", content: "【核心扮演指令】\n主指令" },
    { role: "user", content: "你好" },
    { role: "system", content: "【重要：输出格式要求】" },
  ]);

  const examples = sections.find((section) => section.key === "examples");
  assert.ok(examples);
  assert.equal(examples.items.length, 0);
  assert.match(examples.emptyHint, /未单独注入对话示例/);
});

test("groups group-chat context and visible member history separately", () => {
  const sections = buildPromptPreviewSections([
    { role: "system", content: "【核心扮演指令】\n群聊指令\n\n【角色设定】\n角色甲" },
    {
      role: "system",
      content: '【其他成员的可见历史资料】\n{"speaker_name":"角色乙"}',
    },
    {
      role: "system",
      content: [
        "【当前回合动态背景】",
        '【群聊身份与共同起点】\n{"name":"角色甲"}',
        '【本次发言依据】\n{"speaker_persona_id":1}',
      ].join("\n\n"),
    },
    { role: "user", content: "大家怎么看？" },
    { role: "system", content: "【重要：输出格式要求】\n\n【群聊输出约束】\n仅当前角色发言。" },
  ]);

  const byKey = Object.fromEntries(sections.map((section) => [section.key, section]));
  assert.equal(byKey.history.items[0].label, "群聊成员历史");
  assert.deepEqual(
    Array.from(byKey.dynamic_context.items, (item) => item.label),
    ["群聊身份与共同起点", "本次发言依据"]
  );
  assert.equal(byKey.post_history.items[1].label, "群聊输出约束");
});
