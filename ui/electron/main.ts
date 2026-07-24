/**
 * Electron 主进程入口
 */

import { app, dialog, type MessageBoxOptions } from "electron";

import { registerLive2DProtocol, initLive2DProtocolHandler } from "./live2d-protocol.js";
import {
  createMainWindow,
  getMainWindow,
  getTrustedRendererPolicy,
  initWindowEventListeners,
  openLogWindow,
  sendLogBatch,
} from "./window-manager.js";
import { startCursorTracking, stopCursorTracking } from "./cursor-tracker.js";
import { registerIpcHandlers } from "./ipc-handlers.js";
import { clearChatSettingsCache } from "./chat-settings.js";
import { initAyayaImageProtocolHandler } from "./ayaya-image-protocol.js";
import {
  onBackendUnexpectedExit,
  startBackend,
  stopBackend,
} from "./backend-process.js";
import {
  createBackendRecoveryCoordinator,
  type BackendRecoveryChoice,
  type BackendRecoveryDialogModel,
} from "./backend-recovery.js";
import { createApplicationShutdownCoordinator } from "./application-shutdown.js";
import {
  appendFrontendLog,
  closeLogFiles,
  getRecentLogs,
  initializeLogFiles,
} from "./logging/app-logger.js";
import { registerLogIpcHandlers } from "./logging/log-ipc.js";

const showBackendRecoveryDialog = async (
  model: BackendRecoveryDialogModel,
): Promise<BackendRecoveryChoice> => {
  const options: MessageBoxOptions = {
    type: "error",
    title: model.title,
    message: model.message,
    detail: model.detail,
    buttons: [...model.buttons],
    defaultId: model.defaultId,
    cancelId: model.cancelId,
    noLink: true,
  };
  const mainWindow = getMainWindow();
  const result = mainWindow && !mainWindow.isDestroyed()
    ? await dialog.showMessageBox(mainWindow, options)
    : await dialog.showMessageBox(options);
  return result.response === model.defaultId ? "reconnect" : "exit";
};

const backendRecoveryCoordinator = createBackendRecoveryCoordinator({
  startBackend,
  showDialog: showBackendRecoveryDialog,
  clearSettingsCache: clearChatSettingsCache,
  quit: () => app.quit(),
  logError: (message, error) => appendFrontendLog("error", "backend-recovery", message, error),
});

const applicationShutdownCoordinator = createApplicationShutdownCoordinator({
  beginBackendRecoveryShutdown: () => backendRecoveryCoordinator.beginShutdown(),
  stopCursorTracking,
  stopBackend,
  closeLogs: closeLogFiles,
  quit: () => app.quit(),
  logError: (message, error) => appendFrontendLog("error", "shutdown", message, error),
});

onBackendUnexpectedExit((event) => {
  backendRecoveryCoordinator.handleUnexpectedExit(event);
});

const requestApplicationShutdown = (): void => {
  void applicationShutdownCoordinator.requestShutdown();
};

process.on("SIGINT", requestApplicationShutdown);
process.on("SIGTERM", requestApplicationShutdown);
process.on("uncaughtException", (error) => {
  appendFrontendLog("error", "process", "Electron 主进程发生未捕获异常", error);
  process.exitCode = 1;
  requestApplicationShutdown();
});
process.on("unhandledRejection", (reason) => {
  appendFrontendLog("error", "process", "Electron 主进程发生未处理 Promise 拒绝", reason);
});

// 注册 live2d:// 协议（必须在 app ready 之前）
registerLive2DProtocol();

// 应用就绪后初始化
app.whenReady().then(async () => {
  initializeLogFiles(app.getPath("logs"));
  registerLogIpcHandlers({
    policy: getTrustedRendererPolicy(),
    openLogWindow,
    sendBatch: sendLogBatch,
  });
  registerIpcHandlers();
  openLogWindow();
  appendFrontendLog("info", "startup", "日志控制台已启动，正在启动后端");

  try {
    await startBackend();
  } catch (error) {
    if (applicationShutdownCoordinator.isShuttingDown()) return;
    const recent = getRecentLogs("backend", 50)
      .map((record) => `${record.timestamp} ${record.level.toUpperCase()} ${record.message}`)
      .join("\n");
    const detail = error instanceof Error ? error.message : String(error);
    dialog.showErrorBox(
      "Ayaya 后端启动失败",
      recent ? `${detail}\n\n最近的后端日志：\n${recent}` : detail,
    );
    requestApplicationShutdown();
    return;
  }
  appendFrontendLog("info", "startup", "后端已就绪");
  // 创建主窗口
  const mainWindow = createMainWindow();
  mainWindow.once("closed", requestApplicationShutdown);

  // 初始化 Live2D 协议处理器
  initLive2DProtocolHandler();
  initAyayaImageProtocolHandler();

  // 开始光标追踪
  startCursorTracking();

  // 初始化窗口事件监听
  initWindowEventListeners();
});

app.on("before-quit", (event) => {
  if (applicationShutdownCoordinator.isComplete()) return;
  event.preventDefault();
  requestApplicationShutdown();
});

// 所有窗口关闭时退出（macOS 除外）
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  } else {
    stopCursorTracking();
  }
});
