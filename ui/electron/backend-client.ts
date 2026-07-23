import { AYAYA_BACKEND_BASE_URL } from "./config.js";

let apiToken = "";

/** 配置仅保存在 Electron 主进程内存中的后端认证令牌。 */
export const configureBackendClient = (token: string): void => {
  if (!token) throw new Error("后端 API Token 不能为空");
  apiToken = token;
};

/** 向本地后端发送自动携带认证头的请求。 */
export const backendFetch = (path: string, init: RequestInit = {}): Promise<Response> => {
  if (!apiToken) throw new Error("后端客户端尚未初始化");
  const headers = new Headers(init.headers);
  if (headers.has("Authorization")) {
    throw new Error("调用方不允许覆盖后端认证头");
  }
  headers.set("Authorization", `Bearer ${apiToken}`);
  return globalThis.fetch(`${AYAYA_BACKEND_BASE_URL}${path}`, { ...init, headers });
};
