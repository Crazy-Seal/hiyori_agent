import assert from "node:assert/strict";
import { test } from "node:test";

import { createApplicationShutdownCoordinator } from "../electron/application-shutdown.js";

test("重复关闭请求只停止后端并退出一次", async () => {
  let beginShutdownCalls = 0;
  let stopCursorCalls = 0;
  let stopBackendCalls = 0;
  let quitCalls = 0;
  let releaseBackend: (() => void) | undefined;
  const backendStopped = new Promise<void>((resolve) => {
    releaseBackend = resolve;
  });
  const coordinator = createApplicationShutdownCoordinator({
    beginBackendRecoveryShutdown: () => { beginShutdownCalls += 1; },
    stopCursorTracking: () => { stopCursorCalls += 1; },
    stopBackend: async () => {
      stopBackendCalls += 1;
      await backendStopped;
    },
    quit: () => { quitCalls += 1; },
    logError: () => undefined,
  });

  const first = coordinator.requestShutdown();
  const second = coordinator.requestShutdown();
  assert.equal(first, second);
  assert.equal(stopBackendCalls, 1);
  releaseBackend?.();
  await first;

  assert.equal(beginShutdownCalls, 1);
  assert.equal(stopCursorCalls, 1);
  assert.equal(stopBackendCalls, 1);
  assert.equal(quitCalls, 1);
  assert.equal(coordinator.isComplete(), true);
});

test("后端关闭失败仍完成应用退出", async () => {
  const logged: unknown[] = [];
  let quitCalls = 0;
  const coordinator = createApplicationShutdownCoordinator({
    beginBackendRecoveryShutdown: () => undefined,
    stopCursorTracking: () => undefined,
    stopBackend: async () => {
      throw new Error("shutdown failed");
    },
    quit: () => { quitCalls += 1; },
    logError: (_message, error) => logged.push(error),
  });

  await coordinator.requestShutdown();

  assert.equal(quitCalls, 1);
  assert.equal(logged.length, 1);
});
