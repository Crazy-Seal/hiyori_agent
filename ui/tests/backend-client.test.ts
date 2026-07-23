import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { backendFetch, configureBackendClient } from "../electron/backend-client.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("后端客户端自动添加主进程私有 Bearer Token", async () => {
  configureBackendClient("s".repeat(43));
  let authorization = "";
  globalThis.fetch = async (_input, init) => {
    authorization = new Headers(init?.headers).get("Authorization") ?? "";
    return new Response("ok");
  };

  await backendFetch("/internal/ready");

  assert.equal(authorization, `Bearer ${"s".repeat(43)}`);
});

test("调用方不能覆盖后端认证头", async () => {
  configureBackendClient("s".repeat(43));

  await assert.rejects(
    async () => backendFetch("/internal/ready", { headers: { Authorization: "Bearer evil" } }),
    /不允许覆盖/,
  );
});
