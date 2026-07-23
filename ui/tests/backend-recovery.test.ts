import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createBackendRecoveryCoordinator,
  type BackendRecoveryDialogModel,
} from "../electron/backend-recovery.js";
import type { BackendUnexpectedExit } from "../electron/backend-process.js";

const EXIT_EVENT: BackendUnexpectedExit = {
  exitCode: 1,
  signal: null,
  message: "后端进程意外退出（退出码 1）",
};

const waitUntil = async (predicate: () => boolean): Promise<void> => {
  const deadline = Date.now() + 1_000;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("等待恢复协调器状态超时");
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
};

test("异常退出对话框提供重连和退出并默认重连", async () => {
  const dialogs: BackendRecoveryDialogModel[] = [];
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => undefined,
    showDialog: async (model) => {
      dialogs.push(model);
      return "exit";
    },
    clearSettingsCache: () => undefined,
    quit: () => undefined,
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => dialogs.length === 1);

  assert.deepEqual(dialogs[0], {
    title: "Ayaya 后端意外退出",
    message: "后端进程已停止，聊天、设置和 MCP 功能暂时不可用。",
    detail: "后端进程意外退出（退出码 1）",
    buttons: ["重连", "退出"],
    defaultId: 0,
    cancelId: 1,
  });
});

test("选择退出不会重连且只退出一次", async () => {
  let starts = 0;
  let quits = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => { starts += 1; },
    showDialog: async () => "exit",
    clearSettingsCache: () => undefined,
    quit: () => { quits += 1; },
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => quits === 1);
  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await new Promise<void>((resolve) => setImmediate(resolve));

  assert.equal(starts, 0);
  assert.equal(quits, 1);
});

test("选择重连成功后清理设置缓存并保留应用", async () => {
  let starts = 0;
  let cacheClears = 0;
  let quits = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => { starts += 1; },
    showDialog: async () => "reconnect",
    clearSettingsCache: () => { cacheClears += 1; },
    quit: () => { quits += 1; },
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => cacheClears === 1);

  assert.equal(starts, 1);
  assert.equal(quits, 0);
});

test("重连失败后展示最新错误并继续提供选择", async () => {
  const dialogs: BackendRecoveryDialogModel[] = [];
  const choices = ["reconnect", "exit"] as const;
  let choiceIndex = 0;
  let quits = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => { throw new Error("spawn python EACCES"); },
    showDialog: async (model) => {
      dialogs.push(model);
      return choices[choiceIndex++] ?? "exit";
    },
    clearSettingsCache: () => undefined,
    quit: () => { quits += 1; },
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => quits === 1);

  assert.equal(dialogs.length, 2);
  assert.deepEqual(dialogs[1], {
    title: "Ayaya 后端重连失败",
    message: "无法重新启动后端。",
    detail: "spawn python EACCES",
    buttons: ["重连", "退出"],
    defaultId: 0,
    cancelId: 1,
  });
});

test("多次重连失败后仍可继续重试直到成功", async () => {
  let starts = 0;
  let cacheClears = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => {
      starts += 1;
      if (starts < 3) throw new Error(`失败 ${starts}`);
    },
    showDialog: async () => "reconnect",
    clearSettingsCache: () => { cacheClears += 1; },
    quit: () => undefined,
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => cacheClears === 1);

  assert.equal(starts, 3);
});

test("恢复期间的新退出事件排队且不会并发弹框", async () => {
  let resolveFirstDialog: ((choice: "reconnect" | "exit") => void) | undefined;
  let activeDialogs = 0;
  let maxActiveDialogs = 0;
  let dialogCount = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => undefined,
    showDialog: async () => {
      dialogCount += 1;
      activeDialogs += 1;
      maxActiveDialogs = Math.max(maxActiveDialogs, activeDialogs);
      const choice = dialogCount === 1
        ? await new Promise<"reconnect" | "exit">((resolve) => { resolveFirstDialog = resolve; })
        : "exit";
      activeDialogs -= 1;
      return choice;
    },
    clearSettingsCache: () => undefined,
    quit: () => undefined,
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => dialogCount === 1);
  coordinator.handleUnexpectedExit({
    exitCode: 2,
    signal: null,
    message: "后端进程意外退出（退出码 2）",
  });
  resolveFirstDialog?.("reconnect");
  await waitUntil(() => dialogCount === 2);

  assert.equal(maxActiveDialogs, 1);
});

test("进入退出流程后忽略对话框结果和后续事件", async () => {
  let resolveDialog: ((choice: "reconnect" | "exit") => void) | undefined;
  let starts = 0;
  let dialogCount = 0;
  const coordinator = createBackendRecoveryCoordinator({
    startBackend: async () => { starts += 1; },
    showDialog: async () => {
      dialogCount += 1;
      return new Promise<"reconnect" | "exit">((resolve) => { resolveDialog = resolve; });
    },
    clearSettingsCache: () => undefined,
    quit: () => undefined,
    logError: () => undefined,
  });

  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await waitUntil(() => dialogCount === 1);
  coordinator.beginShutdown();
  resolveDialog?.("reconnect");
  coordinator.handleUnexpectedExit(EXIT_EVENT);
  await new Promise<void>((resolve) => setImmediate(resolve));

  assert.equal(starts, 0);
  assert.equal(dialogCount, 1);
});
