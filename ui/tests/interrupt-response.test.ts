import assert from "node:assert/strict";
import test from "node:test";

import { buildInterruptResponseMeta } from "../src/chat/interrupt-response.js";
import { buildBackendInterruptIdentity } from "../electron/interrupt-response.js";


test("Renderer 分离持久化中断 ID 与流请求 ID", () => {
  const meta = buildInterruptResponseMeta(
    {
      type: "screenshot_request",
      request_id: "interrupt-123",
      message: "允许截屏？",
    },
    "stream-456"
  );

  assert.deepEqual(meta, {
    requestId: "interrupt-123",
    streamRequestId: "stream-456",
  });
});


test("Electron 后端请求只把持久化中断 ID 写入 request_id", () => {
  const identity = buildBackendInterruptIdentity({
    sessionId: "session-a",
    requestId: "interrupt-123",
    streamRequestId: "stream-456",
  });

  assert.deepEqual(identity, {
    session_id: "session-a",
    request_id: "interrupt-123",
  });
  assert.equal(Object.hasOwn(identity, "streamRequestId"), false);
});
