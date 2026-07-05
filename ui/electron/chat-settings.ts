/**
 * 聊天设置 API 调用
 */

import {
  BACKEND_BASE_URL,
  CHAT_HISTORY_PAGE_SIZE,
  CHAT_HISTORY_MAX_PAGES,
} from "./config.js";
import type { ChatSettingsData, ChatHistoryItem, ApiResponse, ToolItem } from "./types.js";
import { getActiveModelRecord } from "./model-manager.js";

/**
 * 缓存的聊天设置
 */
let chatSettingsCache: ChatSettingsData | null = null;

/**
 * 安全解析 JSON
 */
const parseJsonSafe = async <T>(res: Response): Promise<T | null> => {
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
};

/**
 * 根据会话 ID 获取聊天设置
 */
export const fetchChatSettingsBySessionId = async (
  sessionId: string
): Promise<ChatSettingsData> => {
  const url = `${BACKEND_BASE_URL}/chat_settings/${encodeURIComponent(sessionId)}`;
  const res = await fetch(url, {
    method: "GET",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `读取 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<Partial<ChatSettingsData>>>(res);

  if (!result || result.code !== 200 || !result.data) {
    throw new Error(result?.msg || "读取 chat_settings 失败：返回格式错误");
  }

  return {
    session_id: String(result.data.session_id ?? sessionId),
    model_name: String(result.data.model_name ?? ""),
    openai_api_key: String(result.data.openai_api_key ?? ""),
    openai_base_url: String(result.data.openai_base_url ?? ""),
    temperature: typeof result.data.temperature === "number" ? result.data.temperature : 0.7,
    system_prompt: String(result.data.system_prompt ?? ""),
    tools_list: Array.isArray(result.data.tools_list)
      ? result.data.tools_list.map((item) => String(item))
      : [],
    memory_plugins: Array.isArray(result.data.memory_plugins)
      ? result.data.memory_plugins.map((item) => String(item))
      : null,
    name: result.data.name ?? null,
    feature: result.data.feature ?? null,
    character: result.data.character ?? null,
    address: result.data.address ?? null,
    characteristic: result.data.characteristic ?? null,
    constraint: result.data.constraint ?? null,
  };
};

/**
 * 获取聊天历史分页
 */
export const fetchChatHistoryPageBySessionId = async (
  sessionId: string,
  start: number,
  limit: number
): Promise<ChatHistoryItem[]> => {
  const url = `${BACKEND_BASE_URL}/chat_history/${encodeURIComponent(sessionId)}?start=${start}&limit=${limit}`;
  const res = await fetch(url, {
    method: "GET",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `读取 chat_history 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<Array<Partial<ChatHistoryItem>>>>(res);

  if (!result || result.code !== 200 || !Array.isArray(result.data)) {
    throw new Error(result?.msg || "读取 chat_history 失败：返回格式错误");
  }

  return result.data.map((item) => ({
    role: String(item.role ?? ""),
    content: String(item.content ?? ""),
    timestamp: String(item.timestamp ?? ""),
    images: Array.isArray(item.images) ? item.images : undefined,
  }));
};

/**
 * 获取最后 N 条聊天历史
 */
export const fetchChatHistoryLastN = async (
  sessionId: string,
  n: number
): Promise<ChatHistoryItem[]> => {
  const url = `${BACKEND_BASE_URL}/chat_history_last_n/${encodeURIComponent(sessionId)}?n=${n}`;
  const res = await fetch(url, {
    method: "GET",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `读取 chat_history_last_n 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<Array<Partial<ChatHistoryItem>>>>(res);

  if (!result || result.code !== 200 || !Array.isArray(result.data)) {
    throw new Error(result?.msg || "读取 chat_history_last_n 失败：返回格式错误");
  }

  return result.data.map((item) => ({
    role: String(item.role ?? ""),
    content: String(item.content ?? ""),
    timestamp: String(item.timestamp ?? ""),
    images: Array.isArray(item.images) ? item.images : undefined,
  }));
};

/**
 * 从历史记录中获取最新的 AI 消息
 */
const getLatestAiMessageFromHistory = (history: ChatHistoryItem[]): string | null => {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = history[index];
    const role = item.role.trim().toLowerCase();
    const isAi = role === "ai" || role === "assistant";
    const content = item.content.trim();
    if (isAi && content.length > 0) {
      return content;
    }
  }

  return null;
};

/**
 * 获取最新 AI 消息
 */
export const fetchLatestAiMessageBySessionId = async (
  sessionId: string
): Promise<string | null> => {
  // 直接获取最后 20 条记录查找最新 AI 消息
  const history = await fetchChatHistoryLastN(sessionId, 20);
  return getLatestAiMessageFromHistory(history);
};

/**
 * 创建空的聊天设置
 */
export const createEmptyChatSettings = async (sessionId: string): Promise<void> => {
  const payload: ChatSettingsData = {
    session_id: sessionId,
    model_name: "",
    openai_api_key: "",
    openai_base_url: "",
    temperature: 0,
    system_prompt: "",
    tools_list: [],
    memory_plugins: null,
    name: null,
    feature: null,
    character: null,
    address: null,
    characteristic: null,
    constraint: null,
  };

  const res = await fetch(`${BACKEND_BASE_URL}/chat_settings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `创建 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<never>>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "创建 chat_settings 失败：返回格式错误");
  }
};

/**
 * 删除聊天设置
 */
export const deleteChatSettingsBySessionId = async (sessionId: string): Promise<void> => {
  const url = `${BACKEND_BASE_URL}/chat_settings/${encodeURIComponent(sessionId)}`;
  const res = await fetch(url, {
    method: "DELETE",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `删除 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<never>>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "删除 chat_settings 失败：返回格式错误");
  }
};

/**
 * 确保聊天设置已加载
 */
export const ensureChatSettingsLoaded = async (): Promise<ChatSettingsData> => {
  const active = getActiveModelRecord();
  if (chatSettingsCache && chatSettingsCache.session_id === active.sessionId) {
    return chatSettingsCache;
  }

  const fetched = await fetchChatSettingsBySessionId(active.sessionId);
  chatSettingsCache = fetched;
  return fetched;
};

/**
 * 更新聊天设置缓存
 */
export const updateChatSettingsCache = (settings: ChatSettingsData): void => {
  chatSettingsCache = settings;
};

/**
 * 获取缓存的聊天设置
 */
export const getChatSettingsCache = (): ChatSettingsData | null => {
  return chatSettingsCache;
};

/**
 * 清除聊天设置缓存
 */
export const clearChatSettingsCache = (): void => {
  chatSettingsCache = null;
};

/**
 * 更新聊天设置到后端
 */
export const updateChatSettings = async (
  payload: ChatSettingsData
): Promise<ApiResponse<never>> => {
  updateChatSettingsCache(payload);

  const res = await fetch(`${BACKEND_BASE_URL}/chat_settings`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `更新 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<never>>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "更新 chat_settings 失败：返回格式错误");
  }

  return {
    msg: result.msg ?? "success",
    code: 200,
  };
};

/**
 * 获取可用工具列表
 */
export const fetchAvailableTools = async (): Promise<ToolItem[]> => {
  const url = `${BACKEND_BASE_URL}/tools`;
  const res = await fetch(url, { method: "GET" });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `获取工具列表失败: ${res.status}`);
  }

  const result = await parseJsonSafe<ApiResponse<{ tools: ToolItem[] }>>(res);
  if (!result || result.code !== 200 || !result.data?.tools) {
    throw new Error(result?.msg || "获取工具列表失败：返回格式错误");
  }

  return result.data.tools.map((item) => ({
    name: String(item.name ?? ""),
    description: String(item.description ?? ""),
  }));
};
