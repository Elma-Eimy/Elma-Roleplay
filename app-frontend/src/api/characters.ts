import { request, getBaseUrl, DEFAULT_HEADERS, USE_MOCK, getMockDB, setMockDB, getHeaders, getSavedApiKey } from "./config";

// ===================== 类型定义 =====================

export interface CharacterBase {
  name: string;
  avatar_path?: string;
  description: string;
  personality?: string;
  scenario?: string;
  first_mes?: string;
  mes_example?: string;
  creator_notes?: string;
  system_prompt_override?: string;
  post_history_instructions?: string;
  tags?: string[];
  extensions?: Record<string, unknown>;
}

export interface CharacterSummary {
  id: number;
  name: string;
  avatar_path: string;
  description: string;
}

export interface CharacterDetail extends CharacterBase {
  id: number;
  created_at: string;
  lorebooks?: { id: number; name: string }[];
}

export interface ParsedCharacterData extends CharacterBase {}

export interface ParseCharacterResponse {
  message: string;
  data: ParsedCharacterData;
}

export interface CreateCharacterResponse {
  message: string;
  character_id: number;
  name: string;
}

export interface UpdateCharacterResponse {
  message: string;
  character_id: number;
  name: string;
}

export interface DeleteCharacterResponse {
  message: string;
  character_id: number;
  sessions_deleted_count: number;
}

export interface UploadAvatarResponse {
  message: string;
  avatar_path: string;
}

export interface GetCharactersResponse {
  characters: CharacterSummary[];
}

// ===================== API 接口函数 =====================

/**
 * 上传原始头像图片。
 * POST /upload/avatar — multipart/form-data
 */
export async function uploadAvatar(file: File | string): Promise<UploadAvatarResponse> {
  if (USE_MOCK) {
    // 如果是字符串类型，则为临时文件路径（例如来自 uni.chooseImage）。
    const path = typeof file === "string" ? file : URL.createObjectURL(file);
    return {
      message: "Avatar uploaded successfully (Mock)",
      avatar_path: path,
    };
  }

  // 1. 如果是路径字符串，采用 uni.uploadFile 上传真实的二进制文件流
  if (typeof file === "string") {
    return new Promise((resolve, reject) => {
      uni.uploadFile({
        url: `${getBaseUrl()}/upload/avatar`,
        filePath: file,
        name: "file",
        header: getHeaders(),
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try {
              const data = JSON.parse(res.data);
              resolve(data as UploadAvatarResponse);
            } catch (e) {
              reject(new Error(`解析响应失败: ${res.data}`));
            }
          } else {
            reject(new Error(`[uploadAvatar 错误 ${res.statusCode}]: ${res.data}`));
          }
        },
        fail: (err) => {
          reject(new Error(err.errMsg || "头像上传失败"));
        }
      });
    });
  }

  // 2. 兼容传统的 File/Blob 对象（如 H5 网页流）
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${getBaseUrl()}/upload/avatar`, {
    method: "POST",
    headers: getHeaders(),
    body: formData,
    // 注意：不要手动设置 Content-Type 请求头，浏览器会自动处理 boundary 分界符
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`[uploadAvatar Error ${res.status}]: ${errorBody}`);
  }

  return res.json() as Promise<UploadAvatarResponse>;
}

/**
 * 解析角色卡（PNG图片/JSON配置文件）且不保存。
 * POST /characters/parse — multipart/form-data
 */
export async function parseCharacter(file: File | string): Promise<ParseCharacterResponse> {
  if (USE_MOCK) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return {
      message: "Character parsed successfully (Mock)",
      data: {
        name: "Cyber Hacker (Imported)",
        description: "A cynical but brilliant hacker from the year 2077.",
        personality: "Cynical, intelligent, sarcastic",
        scenario: "A dark rainy alleyway in Neon City.",
        first_mes: "Who goes there? Step out of the shadows.",
        mes_example: "{{user}}: Hello.\n{{char}}: Yeah, hi. Make it quick.",
        creator_notes: "Parsed character card notes",
        system_prompt_override: "",
      },
    };
  }

  // 1. 如果是路径字符串，采用 uni.uploadFile 上传真实的二进制文件流
  if (typeof file === "string") {
    return new Promise((resolve, reject) => {
      uni.uploadFile({
        url: `${getBaseUrl()}/characters/parse`,
        filePath: file,
        name: "file",
        header: getHeaders(),
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try {
              const data = JSON.parse(res.data);
              resolve(data as ParseCharacterResponse);
            } catch (e) {
              reject(new Error(`解析响应失败: ${res.data}`));
            }
          } else {
            reject(new Error(`[parseCharacter 错误 ${res.statusCode}]: ${res.data}`));
          }
        },
        fail: (err) => {
          reject(new Error(err.errMsg || "角色卡解析失败"));
        }
      });
    });
  }

  // 2. 兼容传统的 File/Blob 对象（如 H5 网页流）
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${getBaseUrl()}/characters/parse`, {
    method: "POST",
    headers: getHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`[parseCharacter Error ${res.status}]: ${errorBody}`);
  }

  return res.json() as Promise<ParseCharacterResponse>;
}

/**
 * 保存新角色到数据库。
 * POST /characters/create
 */
export async function createCharacter(
  data: CharacterBase
): Promise<CreateCharacterResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const newChar = {
      id: Date.now(),
      ...data,
      created_at: new Date().toISOString(),
    };
    db.characters.push(newChar);
    setMockDB(db);
    return {
      message: "Character created successfully (Mock)",
      character_id: newChar.id,
      name: newChar.name,
    };
  }

  return request<CreateCharacterResponse>("/characters/create", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/**
 * 获取简要角色列表。
 * GET /characters
 */
export async function getCharacters(): Promise<GetCharactersResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    return {
      characters: db.characters.map((c) => ({
        id: c.id,
        name: c.name,
        avatar_path: c.avatar_path || "",
        description: c.description,
      })),
    };
  }

  return request<GetCharactersResponse>("/characters");
}

/**
 * 获取指定角色的完整详情。
 * GET /characters/{character_id}
 */
export async function getCharacter(characterId: number): Promise<CharacterDetail> {
  if (USE_MOCK) {
    const db = getMockDB();
    const char = db.characters.find((c) => c.id === characterId);
    if (!char) {
      throw new Error(`Character ${characterId} not found`);
    }
    return char;
  }

  return request<CharacterDetail>(`/characters/${characterId}`);
}

/**
 * 更新现有角色的设定。
 * PUT /characters/{character_id}
 */
export async function updateCharacter(
  characterId: number,
  data: CharacterBase
): Promise<UpdateCharacterResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    const idx = db.characters.findIndex((c) => c.id === characterId);
    if (idx === -1) {
      throw new Error(`Character ${characterId} not found`);
    }
    db.characters[idx] = {
      ...db.characters[idx],
      ...data,
    };

    // 更新活跃会话中的角色引用
    db.sessions.forEach((s) => {
      if (s.character_id === characterId) {
        s.character.name = data.name;
        s.character.avatar_path = data.avatar_path || "";
      }
    });

    setMockDB(db);
    return {
      message: "Character updated successfully (Mock)",
      character_id: characterId,
      name: data.name,
    };
  }

  return request<UpdateCharacterResponse>(`/characters/${characterId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

/**
 * 删除角色并级联清空其所有会话和记忆。
 * DELETE /characters/{character_id} -> 改为 POST /characters/{character_id}/delete 避开移动端及网关限制
 */
export async function deleteCharacter(
  characterId: number
): Promise<DeleteCharacterResponse> {
  if (USE_MOCK) {
    const db = getMockDB();
    db.characters = db.characters.filter((c) => c.id !== characterId);
    
    const sessionsToDelete = db.sessions.filter((s) => s.character_id === characterId);
    db.sessions = db.sessions.filter((s) => s.character_id !== characterId);
    
    sessionsToDelete.forEach((s) => {
      delete db.messages[s.id];
    });

    setMockDB(db);
    return {
      message: "Character and associated sessions deleted (Mock)",
      character_id: characterId,
      sessions_deleted_count: sessionsToDelete.length,
    };
  }

  return request<DeleteCharacterResponse>(`/characters/${characterId}/delete`, {
    method: "POST",
  });
}

/**
 * 辅助函数：从数据库中存储的相对路径获取头像的完整 URL。
 */
export function getAvatarUrl(avatarPath: string): string {
  if (!avatarPath) return "/static/default-avatar.png";
  if (avatarPath.startsWith("blob:") || avatarPath.startsWith("http://") || avatarPath.startsWith("https://") || avatarPath.startsWith("file://") || avatarPath.startsWith("wxfile://")) {
    return avatarPath;
  }
  const filename = avatarPath.replace(/^.*[\\/]/, "");
  let url = `${getBaseUrl()}/assets/avatars/${filename}`;
  const apiKey = getSavedApiKey();
  if (apiKey) {
    url += `?token=${encodeURIComponent(apiKey)}`;
  }
  return url;
}
