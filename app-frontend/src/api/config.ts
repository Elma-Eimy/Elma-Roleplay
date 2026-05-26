/**
 * api/config.ts
 * 统一的 API 全局配置 — 从环境变量读取或默认回退到本地开发服务器。
 */

// 动态获取及保存 API 基础 URL 逻辑，方便在部署时 runtime 修改端口及地址
export function getSavedBaseUrl(): string {
  try {
    const saved = uni.getStorageSync("api_base_url");
    if (saved) return saved;
  } catch (e) {}
  return import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
}

export function getBaseUrl(): string {
  return getSavedBaseUrl();
}

export function setSavedBaseUrl(newUrl: string) {
  try {
    const trimmedUrl = newUrl.replace(/\/+$/, "");
    uni.setStorageSync("api_base_url", trimmedUrl);
  } catch (e) {
    console.error("Failed to save base URL", e);
  }
}

export const DEFAULT_HEADERS: Record<string, string> = {
  "Content-Type": "application/json",
};

/** 动态获取请求头的辅助函数，若配置了认证密钥则会自动携带 */
export function getHeaders(customHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    ...customHeaders,
  };
  
  try {
    const key = uni.getStorageSync("api_access_key");
    if (key) {
      headers["X-API-Key"] = key;
    }
  } catch (e) {
    console.error("Failed to read api_access_key", e);
  }
  
  return headers;
}

/** 是否在离线 Mock 模拟模式下运行应用的开关 */
export const USE_MOCK = false;

const MOCK_DB_KEY = "ai_roleplay_mock_db";

export interface MockDatabase {
  characters: any[];
  sessions: any[];
  messages: Record<number, any[]>; // 会话ID -> 消息数组映射 (sessionId -> Message[])
}

function getInitialMockDB(): MockDatabase {
  const characters = [
    {
      id: 1,
      name: "AI Assistant",
      avatar_path: "",
      description: "A helpful, friendly AI ready to assist you with any task.",
      personality: "Helpful, friendly, organized",
      scenario: "A clean, modern virtual office",
      first_mes: "Hello! I am your AI assistant. How can I help you today?",
      mes_example: "{{user}}: Can you organize my list?\n{{char}}: Sure! Let me write down the points for you.",
      creator_notes: "Default helper persona",
      system_prompt_override: "",
      created_at: new Date(Date.now() - 86400000).toISOString(),
    },
    {
      id: 2,
      name: "Cyber Hacker",
      avatar_path: "",
      description: "A cynical but brilliant hacker from the year 2077.",
      personality: "Cynical, intelligent, sarcastic, cautious",
      scenario: "A dark rainy alleyway in Neon City.",
      first_mes: "Who goes there? Step out of the shadows.",
      mes_example: "{{user}}: Hello.\n{{char}}: Yeah, hi. Make it quick.",
      creator_notes: "Cyberpunk roleplay persona",
      system_prompt_override: "",
      created_at: new Date(Date.now() - 86400000).toISOString(),
    }
  ];

  const sessions = [
    {
      id: 1,
      title: "Project Zero Dawn",
      character_id: 2,
      parent_session_id: null,
      created_at: new Date(Date.now() - 3600000).toISOString(),
      updated_at: new Date().toISOString(),
      persona: {
        id: 101,
        character_id: 2,
        affection_score: 10,
        cognition_state: "The user asked for help. Cyber Hacker is cautious but helpful.",
        current_mood: "Calm",
        current_scenario_override: null
      },
      character: {
        id: 2,
        name: "Cyber Hacker",
        avatar_path: ""
      }
    },
    {
      id: 2,
      title: "Daily Tasks",
      character_id: 1,
      parent_session_id: null,
      created_at: new Date(Date.now() - 7200000).toISOString(),
      updated_at: new Date(Date.now() - 3600000).toISOString(),
      persona: {
        id: 102,
        character_id: 1,
        affection_score: 5,
        cognition_state: "The user is organizing schedule.",
        current_mood: "Happy",
        current_scenario_override: null
      },
      character: {
        id: 1,
        name: "AI Assistant",
        avatar_path: ""
      }
    }
  ];

  const messages: Record<number, any[]> = {
    1: [
      {
        id: 1001,
        role: "assistant",
        content: "Who goes there? Step out of the shadows.",
        emotion_tag: "Calm",
        affection_change: 0,
        created_at: new Date(Date.now() - 3600000).toISOString()
      },
      {
        id: 1002,
        role: "user",
        content: "Hello. I need help accessing the Arasaka mainframe.",
        emotion_tag: null,
        affection_change: null,
        created_at: new Date(Date.now() - 3000000).toISOString()
      },
      {
        id: 1003,
        role: "assistant",
        content: "I found a backdoor in the mainframe.",
        emotion_tag: "Serious",
        affection_change: 2,
        created_at: new Date(Date.now() - 2400000).toISOString()
      }
    ],
    2: [
      {
        id: 2001,
        role: "assistant",
        content: "Hello! I am your AI assistant. How can I help you today?",
        emotion_tag: "Happy",
        affection_change: 0,
        created_at: new Date(Date.now() - 7200000).toISOString()
      },
      {
        id: 2002,
        role: "user",
        content: "Can you help me check my calendar?",
        emotion_tag: null,
        affection_change: null,
        created_at: new Date(Date.now() - 6000000).toISOString()
      },
      {
        id: 2003,
        role: "assistant",
        content: "Your schedule has been updated.",
        emotion_tag: "Efficient",
        affection_change: 1,
        created_at: new Date(Date.now() - 5400000).toISOString()
      }
    ]
  };

  return { characters, sessions, messages };
}

/** 从 uni 缓存存储中获取或初始化 Mock 模拟数据库状态 */
export function getMockDB(): MockDatabase {
  let dbStr = "";
  try {
    dbStr = uni.getStorageSync(MOCK_DB_KEY);
  } catch (e) {
    console.error("Failed to read storage", e);
  }
  
  if (!dbStr) {
    const db = getInitialMockDB();
    setMockDB(db);
    return db;
  }
  return JSON.parse(dbStr);
}

/** 保存 Mock 模拟数据库状态到 uni 缓存存储 */
export function setMockDB(db: MockDatabase) {
  try {
    uni.setStorageSync(MOCK_DB_KEY, JSON.stringify(db));
  } catch (e) {
    console.error("Failed to write storage", e);
  }
}

/** 带有统一错误处理的通用 uni.request 请求封装 */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${getBaseUrl()}${endpoint}`;
  const headers = getHeaders({
    ...DEFAULT_HEADERS,
    ...((options.headers as Record<string, string>) ?? {}),
  });

  const method = (options.method ?? "GET") as "GET" | "POST" | "PUT" | "DELETE";
  let data: any = undefined;
  if (options.body) {
    if (typeof options.body === "string") {
      try {
        data = JSON.parse(options.body);
      } catch (e) {
        data = options.body;
      }
    } else {
      data = options.body;
    }
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url,
      method,
      header: headers,
      data,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T);
        } else {
          const errMsg = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
          reject(new Error(`[API Error ${res.statusCode}] ${endpoint}: ${errMsg}`));
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || "网络连接失败"));
      }
    });
  });
}
