import type { MCPToolApprovalInterruptData } from "../../shared-types.js";

/**
 * 将 MCP 审批中断格式化为用户可核对的确认文本。
 *
 * @param interrupt - 包含 Server、工具说明和调用参数的中断数据。
 * @returns 展示在一次性审批对话框中的文本。
 */
export const formatMcpApprovalMessage = (interrupt: MCPToolApprovalInterruptData): string => {
  const details = interrupt.data;
  return `${details.server_name} 请求调用工具 ${details.tool_name}\n\n${details.description || "无工具描述"}\n\n参数：\n${JSON.stringify(details.arguments, null, 2)}`;
};
