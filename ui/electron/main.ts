/**
 * Electron 主进程入口
 */

import { app, dialog, type MessageBoxOptions } from "electron";

import { registerLive2DProtocol, initLive2DProtocolHandler } from "./live2d-protocol.js";
import { createMainWindow, getMainWindow, initWindowEventListeners } from "./window-manager.js";
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
  logError: (message, error) => console.error(message, error),
});

const applicationShutdownCoordinator = createApplicationShutdownCoordinator({
  beginBackendRecoveryShutdown: () => backendRecoveryCoordinator.beginShutdown(),
  stopCursorTracking,
  stopBackend,
  quit: () => app.quit(),
  logError: (message, error) => console.error(message, error),
});

onBackendUnexpectedExit((event) => {
  backendRecoveryCoordinator.handleUnexpectedExit(event);
});

const requestApplicationShutdown = (): void => {
  void applicationShutdownCoordinator.requestShutdown();
};

process.on("SIGINT", requestApplicationShutdown);
process.on("SIGTERM", requestApplicationShutdown);

// 注册 live2d:// 协议（必须在 app ready 之前）
registerLive2DProtocol();

// 应用就绪后初始化
app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (error) {
    if (applicationShutdownCoordinator.isShuttingDown()) return;
    dialog.showErrorBox("Ayaya 后端启动失败", error instanceof Error ? error.message : String(error));
    requestApplicationShutdown();
    return;
  }
  // 创建主窗口
  createMainWindow();

  // 初始化 Live2D 协议处理器
  initLive2DProtocolHandler();
  initAyayaImageProtocolHandler();

  // 注册 IPC 处理器
  registerIpcHandlers();

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
