import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveBackendBaseUrl } from "../electron/config.js";

test("后端地址默认使用固定回环端口", () => {
  assert.equal(resolveBackendBaseUrl({}), "http://127.0.0.1:8000");
});

test("AYAYA_BACKEND_BASE_URL 可以覆盖默认地址", () => {
  assert.equal(
    resolveBackendBaseUrl({ AYAYA_BACKEND_BASE_URL: "http://127.0.0.1:9000" }),
    "http://127.0.0.1:9000",
  );
});

test("旧 BACKEND_BASE_URL 不再生效", () => {
  assert.equal(
    resolveBackendBaseUrl({ BACKEND_BASE_URL: "http://127.0.0.1:9000" }),
    "http://127.0.0.1:8000",
  );
});
