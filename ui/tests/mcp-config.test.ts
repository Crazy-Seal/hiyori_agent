import assert from "node:assert/strict";
import test from "node:test";

import { buildEnabledServerPolicy, fingerprintMcpConfig } from "../src/settings/mcp-config.js";
import type { MCPServerConfig } from "../shared-types.js";

test("首次启用服务器时已发现工具默认 ask", () => {
  assert.deepEqual(buildEnabledServerPolicy(undefined, ["read_file", "write_file"]), {
    enabled: true,
    tools: { read_file: "ask", write_file: "ask" },
  });
});

test("已启用服务器的新发现工具默认 ask", () => {
  const policy = buildEnabledServerPolicy(
    { enabled: true, tools: { read_file: "allow" } },
    ["read_file", "delete_file"]
  );
  assert.deepEqual(policy, {
    enabled: true,
    tools: { read_file: "allow", delete_file: "ask" },
  });
});

test("曾启用后又关闭的服务器，新工具仍默认 ask", () => {
  const policy = buildEnabledServerPolicy(
    { enabled: false, tools: { read_file: "ask" } },
    ["read_file", "new_tool"]
  );
  assert.equal(policy.tools.new_tool, "ask");
});

test("MCP 配置指纹不受 env 键顺序影响", () => {
  const base: MCPServerConfig = {
    id: "fs",
    name: "Filesystem",
    enabled: true,
    transport: "stdio",
    command: "node",
    args: ["server.js"],
    cwd: null,
    env: { TOKEN: "secret", MODE: "local" },
    connect_timeout_seconds: 15,
    call_timeout_seconds: 60,
  };
  assert.equal(
    fingerprintMcpConfig(base),
    fingerprintMcpConfig({ ...base, env: { MODE: "local", TOKEN: "secret" } })
  );
  assert.equal(
    fingerprintMcpConfig(base),
    fingerprintMcpConfig({ ...base, name: "Renamed", enabled: false, call_timeout_seconds: 30 })
  );
});
