import assert from "node:assert/strict";
import test from "node:test";

import { formatMcpApprovalMessage } from "../src/chat/mcp-approval.js";

test("MCP 工具确认框展示服务、工具和完整参数", () => {
  const message = formatMcpApprovalMessage({
    type: "mcp_tool_approval_request",
    request_id: "request-1",
    message: "confirm",
    data: {
      server_id: "filesystem",
      server_name: "Filesystem",
      tool_name: "write_file",
      description: "写入文件",
      arguments: { path: "README.md", content: "hello" },
    },
  });

  assert.match(message, /Filesystem/);
  assert.match(message, /write_file/);
  assert.match(message, /README\.md/);
  assert.match(message, /hello/);
});
