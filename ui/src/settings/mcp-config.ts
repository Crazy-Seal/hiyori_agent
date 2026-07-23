import type { MCPServerConfig, MCPToolPolicy } from "../../shared-types.js";

type ServerPolicy = {
  enabled: boolean;
  tools: Record<string, MCPToolPolicy>;
  identity_fingerprint?: string | null;
};

/**
 * 递归稳定化对象键顺序，便于比较配置内容。
 *
 * @param value - 待稳定化的任意 JSON 兼容值。
 * @returns 保持数组顺序且对象键已排序的值。
 */
const stableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableValue(item)])
    );
  }
  return value;
};

/**
 * 生成用于前端测试状态绑定的 MCP 配置指纹。
 *
 * @param config - 当前编辑的 MCP Server 配置。
 * @returns 可稳定比较的配置序列化字符串。
 */
export const fingerprintMcpConfig = (config: MCPServerConfig): string =>
  JSON.stringify(stableValue(config.transport === "stdio" ? {
    id: config.id,
    transport: config.transport,
    command: config.command,
    args: config.args,
    cwd: config.cwd ?? null,
    env: config.env,
    connect_timeout_seconds: config.connect_timeout_seconds,
  } : {
    id: config.id,
    transport: config.transport,
    url: config.url,
    headers: config.headers,
    connect_timeout_seconds: config.connect_timeout_seconds,
  }));

/**
 * 构造启用状态的模型级 MCP Server 权限。
 *
 * @param current - 当前已保存的 Server 权限。
 * @param toolNames - Server 当前暴露的工具名称。
 * @returns 保留已有策略并将新工具默认设为 ask 的权限对象。
 */
export const buildEnabledServerPolicy = (
  current: ServerPolicy | undefined,
  toolNames: string[]
): ServerPolicy => {
  return {
    enabled: true,
    tools: Object.fromEntries(
      toolNames.map((name) => [name, current?.tools[name] ?? "ask"])
    ),
    ...(current?.identity_fingerprint
      ? { identity_fingerprint: current.identity_fingerprint }
      : {}),
  };
};
