import { backendFetch } from "./backend-client.js";
import type {
  ApiResponse,
  MCPServerConfig,
  MCPServerView,
  MCPTestResult,
  MCPToolInfo,
} from "../shared-types.js";

/**
 * 请求本地后端的 MCP API 并提取统一响应中的数据。
 *
 * @param path - 相对于后端根地址的 API 路径。
 * @param init - 可选的 Fetch 请求参数。
 * @returns 后端统一响应中的业务数据。
 * @throws {Error} HTTP 状态、响应结构或业务状态不合法时抛出。
 */
const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await backendFetch(path, init);
  const result = await response.json().catch(() => null) as (ApiResponse<T> & { detail?: string }) | null;
  if (!response.ok || !result || result.code !== 200 || result.data === undefined) {
    throw new Error(result?.msg || result?.detail || `MCP 请求失败: ${response.status}`);
  }
  return result.data;
};

/**
 * 构造可选携带 JSON 请求体的 Fetch 参数。
 *
 * @param method - HTTP 方法。
 * @param body - 可选的 JSON 请求体。
 * @returns 可直接传给 Fetch 的请求参数。
 */
const jsonInit = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: body === undefined ? undefined : { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

/**
 * 获取全部 MCP Server 及其运行状态。
 *
 * @returns MCP Server 视图列表。
 */
export const fetchMcpServers = (): Promise<MCPServerView[]> => request("/mcp/servers");

/**
 * 测试 MCP Server 配置而不保存。
 *
 * @param config - 待测试的 Server 配置。
 * @returns 连接状态、instructions 和工具目录。
 */
export const testMcpServer = (config: MCPServerConfig): Promise<MCPTestResult> =>
  request("/mcp/servers/test", jsonInit("POST", config));

/**
 * 创建 MCP Server。
 *
 * @param config - 待创建的 Server 配置。
 * @returns 新 Server 的设置页视图。
 */
export const createMcpServer = (config: MCPServerConfig): Promise<MCPServerView> =>
  request("/mcp/servers", jsonInit("POST", config));

/**
 * 更新指定 MCP Server。
 *
 * @param serverId - 原 MCP Server ID。
 * @param config - 更新后的完整配置。
 * @returns 更新后的设置页视图。
 */
export const updateMcpServer = (
  serverId: string,
  config: MCPServerConfig
): Promise<MCPServerView> =>
  request(`/mcp/servers/${encodeURIComponent(serverId)}`, jsonInit("PUT", config));

/**
 * 删除 MCP Server 并清理模型引用。
 *
 * @param serverId - 待删除的 MCP Server ID。
 * @returns 权限引用受到清理的会话 ID。
 */
export const deleteMcpServer = (serverId: string): Promise<{ affected_sessions: string[] }> =>
  request(`/mcp/servers/${encodeURIComponent(serverId)}`, jsonInit("DELETE"));

/**
 * 重新连接指定 MCP Server。
 *
 * @param serverId - 待重连的 MCP Server ID。
 * @returns 重连后的设置页视图。
 */
export const reconnectMcpServer = (serverId: string): Promise<MCPServerView> =>
  request(`/mcp/servers/${encodeURIComponent(serverId)}/reconnect`, jsonInit("POST"));

/**
 * 获取指定 MCP Server 的工具目录。
 *
 * @param serverId - MCP Server ID。
 * @returns Server 当前已缓存的工具信息。
 */
export const fetchMcpServerTools = (serverId: string): Promise<MCPToolInfo[]> =>
  request(`/mcp/servers/${encodeURIComponent(serverId)}/tools`);
