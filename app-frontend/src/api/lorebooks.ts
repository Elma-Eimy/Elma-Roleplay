import { request, getBaseUrl, getHeaders, USE_MOCK, getMockDB, setMockDB } from "./config";

export interface LorebookEntry {
  keys: string[];
  content: string;
  enabled: boolean;
  constant: boolean;
  case_sensitive: boolean;
  selective: boolean;
  secondary_keys: string[];
  position: string;
  insertion_order: number;
}

export interface LorebookSummary {
  id: number;
  name: string;
  description: string;
  scan_depth?: number;
  token_budget?: number;
  recursive_scanning?: boolean;
  entries_count: number;
  created_at?: string;
}

export interface LorebookDetail extends LorebookSummary {
  entries: LorebookEntry[];
}

/**
 * 获取所有独立世界书列表
 */
export async function getLorebooks(): Promise<{ lorebooks: LorebookSummary[] }> {
  if (USE_MOCK) {
    const db = getMockDB();
    return {
      lorebooks: (db.lorebooks || []).map((lb: any) => ({
        id: lb.id,
        name: lb.name,
        description: lb.description || "",
        entries_count: (lb.entries || []).length,
      })),
    };
  }
  return request<{ lorebooks: LorebookSummary[] }>("/lorebooks");
}

/**
 * 获取单个独立世界书的详细信息
 */
export async function getLorebook(id: number): Promise<LorebookDetail> {
  if (USE_MOCK) {
    const db = getMockDB();
    const lb = (db.lorebooks || []).find((l: any) => l.id === id);
    if (!lb) throw new Error("Lorebook not found");
    return lb;
  }
  return request<LorebookDetail>(`/lorebooks/${id}`);
}

/**
 * 更新独立世界书
 */
export async function updateLorebook(
  id: number,
  data: Partial<LorebookDetail>
): Promise<{ message: string; lorebook_id: number; entries_count: number }> {
  if (USE_MOCK) {
    const db = getMockDB();
    if (!db.lorebooks) db.lorebooks = [];
    const idx = db.lorebooks.findIndex((l: any) => l.id === id);
    if (idx === -1) throw new Error("Lorebook not found");
    db.lorebooks[idx] = { ...db.lorebooks[idx], ...data };
    setMockDB(db);
    return {
      message: "Lorebook updated successfully (Mock)",
      lorebook_id: id,
      entries_count: (data.entries || []).length,
    };
  }
  return request<{ message: string; lorebook_id: number; entries_count: number }>(
    `/lorebooks/${id}`,
    {
      method: "PUT",
      body: JSON.stringify(data),
    }
  );
}

/**
 * 删除独立世界书
 */
export async function deleteLorebook(id: number): Promise<{ message: string; lorebook_id: number }> {
  if (USE_MOCK) {
    const db = getMockDB();
    db.lorebooks = (db.lorebooks || []).filter((l: any) => l.id !== id);
    // 级联清除 MockDB 角色绑定关系
    (db.characters || []).forEach((c: any) => {
      if (c.extensions && c.extensions.lorebook_ids) {
        c.extensions.lorebook_ids = c.extensions.lorebook_ids.filter((lid: number) => lid !== id);
      }
    });
    setMockDB(db);
    return {
      message: "Lorebook deleted successfully (Mock)",
      lorebook_id: id,
    };
  }
  return request<{ message: string; lorebook_id: number }>(`/lorebooks/${id}/delete`, {
    method: "POST",
  });
}

/**
 * 上传导入世界书 JSON 文件
 */
export async function importLorebook(file: File | string): Promise<{
  message: string;
  lorebook_id: number;
  name: string;
  entries_count: number;
}> {
  if (USE_MOCK) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    const db = getMockDB();
    const mockId = Date.now();
    const mockLb = {
      id: mockId,
      name: "导入的设定集 (Mock)",
      description: "Mock import description",
      entries: [
        {
          keys: ["测试"],
          content: "这是一个测试条目",
          enabled: true,
          constant: false,
          case_sensitive: false,
          selective: false,
          secondary_keys: [],
          position: "after_char",
          insertion_order: 100,
        },
      ],
    };
    if (!db.lorebooks) db.lorebooks = [];
    db.lorebooks.push(mockLb);
    setMockDB(db);
    return {
      message: "Lorebook imported successfully (Mock)",
      lorebook_id: mockId,
      name: mockLb.name,
      entries_count: mockLb.entries.length,
    };
  }

  // 1. 如果是路径字符串，采用 uni.uploadFile 上传真实的二进制文件流
  if (typeof file === "string") {
    return new Promise((resolve, reject) => {
      uni.uploadFile({
        url: `${getBaseUrl()}/lorebooks/import`,
        filePath: file,
        name: "file",
        header: getHeaders(),
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try {
              const data = JSON.parse(res.data);
              resolve(data);
            } catch (e) {
              reject(new Error(`解析响应失败: ${res.data}`));
            }
          } else {
            reject(new Error(`[importLorebook 错误 ${res.statusCode}]: ${res.data}`));
          }
        },
        fail: (err) => {
          reject(new Error(err.errMsg || "世界书导入失败"));
        },
      });
    });
  }

  // 2. 兼容 H5 网页的 File/Blob 对象
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${getBaseUrl()}/lorebooks/import`, {
    method: "POST",
    headers: getHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`[importLorebook Error ${res.status}]: ${errorBody}`);
  }

  return res.json();
}

/**
 * 绑定角色卡到独立世界书
 */
export async function bindLorebook(characterId: number, lorebookId: number): Promise<{ message: string }> {
  if (USE_MOCK) {
    const db = getMockDB();
    const char = db.characters.find((c: any) => c.id === characterId);
    if (!char) throw new Error("Character not found");
    if (!char.extensions) char.extensions = {};
    if (!char.extensions.lorebook_ids) char.extensions.lorebook_ids = [];
    if (!char.extensions.lorebook_ids.includes(lorebookId)) {
      char.extensions.lorebook_ids.push(lorebookId);
    }
    setMockDB(db);
    return { message: "Successfully bound (Mock)" };
  }
  return request<{ message: string }>(`/lorebooks/characters/${characterId}/bind/${lorebookId}`, {
    method: "POST",
  });
}

/**
 * 解除绑定角色卡与独立世界书
 */
export async function unbindLorebook(characterId: number, lorebookId: number): Promise<{ message: string }> {
  if (USE_MOCK) {
    const db = getMockDB();
    const char = db.characters.find((c: any) => c.id === characterId);
    if (!char) throw new Error("Character not found");
    if (char.extensions && char.extensions.lorebook_ids) {
      char.extensions.lorebook_ids = char.extensions.lorebook_ids.filter((id: number) => id !== lorebookId);
    }
    setMockDB(db);
    return { message: "Successfully unbound (Mock)" };
  }
  return request<{ message: string }>(`/lorebooks/characters/${characterId}/unbind/${lorebookId}`, {
    method: "POST",
  });
}
