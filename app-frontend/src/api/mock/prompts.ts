import type { CompiledPromptResponse } from "../../types/prompts";

export async function getCompiledPrompt(
  sessionId: number
): Promise<CompiledPromptResponse> {
  return {
    messages: [
      { role: "system", content: "【系统提示词（编译预设）】\n你扮演Cyber Hacker...\n\n【重要：输出格式要求】\n<reply>回复内容</reply>\n<status emotion=\"开心\" affection_change=\"0\"/>" },
      { role: "assistant", content: "<reply>你好，我是赛博黑客。找我有什么事？</reply>\n<status emotion=\"平静\" affection_change=\"0\"/>" },
      { role: "user", content: "【系统提供的上下文背景信息（大模型请注意结合以下背景进行角色扮演回复）：】\n<current_scenario>\n赛博朋克霓虹城市酒吧。\n</current_scenario>\n\n【当前用户的最新消息：】\n你好，请帮我分析一下这个系统漏洞。" }
    ],
    token_estimate: {
      characters: 18420,
      estimated_tokens: 12800,
      lower_bound: 9760,
      upper_bound: 16720,
      method: "heuristic_v1",
      is_exact: false,
      sections: {
        character: { characters: 8200, estimated_tokens: 6100, lower_bound: 4800, upper_bound: 7600 },
        recent_history: { characters: 6000, estimated_tokens: 3900, lower_bound: 3000, upper_bound: 5000 },
        scenario: { characters: 300, estimated_tokens: 220, lower_bound: 150, upper_bound: 350 },
        cognition: { characters: 500, estimated_tokens: 350, lower_bound: 250, upper_bound: 500 },
        status: { characters: 120, estimated_tokens: 90, lower_bound: 60, upper_bound: 150 },
        lorebook: { characters: 900, estimated_tokens: 600, lower_bound: 400, upper_bound: 850 },
        long_term_memory: { characters: 1000, estimated_tokens: 700, lower_bound: 500, upper_bound: 1000 },
        graph: { characters: 400, estimated_tokens: 280, lower_bound: 190, upper_bound: 420 },
        current_user_message: { characters: 800, estimated_tokens: 520, lower_bound: 380, upper_bound: 750 },
        other: { characters: 200, estimated_tokens: 40, lower_bound: 30, upper_bound: 100 }
      }
    }
  };
}
