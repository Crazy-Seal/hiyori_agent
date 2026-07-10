/**
 * IPC 处理器注册
 */

import { ipcMain, BrowserWindow, dialog, net, desktopCapturer, screen, type IpcMainInvokeEvent } from "electron";
import fs from "node:fs";
import path from "node:path";

import { BACKEND_BASE_URL, CHAT_REQUEST_TIMEOUT_MS, FRONTEND_SETTINGS_PATH } from "./config.js";
import { consumeSseStream } from "./sse-stream.js";
import type {
  ChatSettingsData,
  ModelTransformPayload,
  ToolItem,
  ModelChangedPayload,
  ModelTransformChangedPayload,
  ChatChunkPayload,
  ScreenActionRequest,
  ScreenActionResult,
  FrontendSettings,
  ChatResult,
} from "./types.js";
import {
  loadModelConfig,
  saveModelConfig,
  getActiveModelRecord,
  resolveModelUrl,
  resolveRootDirAbsolute,
  inspectImportSource,
  resolveUniqueModelDir,
  copyDirectory,
  findModel3JsonRelativePath,
  createModelRecord,
  sanitizeModelName,
} from "./model-manager.js";
import {
  ensureChatSettingsLoaded,
  createEmptyChatSettings,
  deleteChatSettingsBySessionId,
  fetchLatestAiMessageBySessionId,
  fetchChatHistoryPageBySessionId,
  fetchChatHistoryLastN,
  updateChatSettings,
  clearChatSettingsCache,
  fetchAvailableTools,
  fetchAvailablePlugins,
} from "./chat-settings.js";
import { getMainWindow, getSettingsWindow, openSettingsWindow, openImagePreviewWindow } from "./window-manager.js";

/**
 * 通知模型已更改（同时通知主窗口和设置窗口）
 */
const notifyModelChanged = (): void => {
  const active = getActiveModelRecord();
  const payload: ModelChangedPayload = {
    id: active.id,
    name: active.name,
    sessionId: active.sessionId,
    modelUrl: resolveModelUrl(active),
    offsetX: active.offsetX ?? 0,
    offsetY: active.offsetY ?? 0,
    userScale: active.userScale ?? 1,
    followCursor: active.followCursor ?? true,
  };

  // 通知主窗口
  const mainWindow = getMainWindow();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("desktop-pet:model-changed", payload);
  }

  // 通知设置窗口
  const settingsWindow = getSettingsWindow();
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send("desktop-pet:model-changed", payload);
  }
};

/**
 * 通知主窗口模型变换已更改
 */
const notifyModelTransformChanged = (model: {
  id: string;
  offsetX?: number;
  offsetY?: number;
  userScale?: number;
  followCursor?: boolean;
}): void => {
  const mainWindow = getMainWindow();
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const payload: ModelTransformChangedPayload = {
    id: model.id,
    offsetX: model.offsetX ?? 0,
    offsetY: model.offsetY ?? 0,
    userScale: model.userScale ?? 1,
    followCursor: model.followCursor ?? true,
  };

  mainWindow.webContents.send("desktop-pet:model-transform-changed", payload);
};

const streamBackendResponse = async (
  event: IpcMainInvokeEvent,
  res: Response,
  requestId: string | undefined,
  errorFallback: string
): Promise<ChatResult> => {
  if (!res.body) {
    throw new Error("API error: missing response stream");
  }
  return await consumeSseStream(
    res.body,
    {
      onChunk: (chunk, aggregated) => {
        if (!requestId) return;
        const chunkPayload: ChatChunkPayload = { requestId, chunk, aggregated };
        event.sender.send("desktop-pet:chat-chunk", chunkPayload);
      },
      onToolCall: (toolName) => {
        if (!requestId) return;
        event.sender.send("desktop-pet:chat-tool-call", { requestId, toolName });
      },
      onInterrupt: (interrupt) => {
        event.sender.send("desktop-pet:chat-interrupt", interrupt);
      },
    },
    errorFallback,
  );
};

const performScreenAction = async (payload: ScreenActionRequest): Promise<ScreenActionResult> => {
  const coordinates = payload.coordinates;
  if (!coordinates || typeof coordinates.x_ratio !== "number" || typeof coordinates.y_ratio !== "number") {
    return { executed: false, error: "缺少有效的屏幕坐标" };
  }

  try {
    const nut = await import("@nut-tree-fork/nut-js");
    const display = screen.getPrimaryDisplay();
    const bounds = display.bounds;
    const x = Math.round(bounds.x + coordinates.x_ratio * bounds.width);
    const y = Math.round(bounds.y + coordinates.y_ratio * bounds.height);
    const point = new nut.Point(x, y);

    await nut.mouse.setPosition(point);
    if (payload.operation === "click") {
      await nut.mouse.click(nut.Button.LEFT);
    } else if (payload.operation === "double") {
      await nut.mouse.doubleClick(nut.Button.LEFT);
    } else if (payload.operation === "right") {
      await nut.mouse.click(nut.Button.RIGHT);
    } else if (payload.operation === "scroll") {
      if (payload.scroll_direction === "up") {
        await nut.mouse.scrollUp(6);
      } else if (payload.scroll_direction === "down") {
        await nut.mouse.scrollDown(6);
      } else {
        return { executed: false, error: "滚动操作缺少方向" };
      }
    } else {
      return { executed: false, error: `不支持的操作方式: ${payload.operation}` };
    }

    if (payload.text) {
      await nut.keyboard.type(payload.text);
      if (payload.press_enter) {
        await nut.keyboard.pressKey(nut.Key.Enter);
        await nut.keyboard.releaseKey(nut.Key.Enter);
      }
    }

    return { executed: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("[ControlScreen] 屏幕操作失败:", error);
    return { executed: false, error: message };
  }
};

/**
 * 注册 IPC 处理器
 */
export const registerIpcHandlers = (): void => {
  // 鼠标穿透控制
  ipcMain.on("desktop-pet:set-mouse-passthrough", (event, enabled: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? getMainWindow();
    if (!win) {
      return;
    }

    win.setIgnoreMouseEvents(Boolean(enabled), { forward: true });
  });

  // 指针交互控制
  ipcMain.on("desktop-pet:set-pointer-interactive", (event, enabled: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? getMainWindow();
    if (!win) {
      return;
    }

    win.setIgnoreMouseEvents(!Boolean(enabled), { forward: true });
  });

  // 获取当前激活的模型
  ipcMain.handle("desktop-pet:get-active-model", () => {
    const active = getActiveModelRecord();
    return {
      id: active.id,
      name: active.name,
      sessionId: active.sessionId,
      modelUrl: resolveModelUrl(active),
      offsetX: active.offsetX ?? 0,
      offsetY: active.offsetY ?? 0,
      userScale: active.userScale ?? 1,
      followCursor: active.followCursor ?? true,
      motionConfig: active.motionConfig ?? [],
      entry: active.entry,
    };
  });

  // 获取模型配置
  ipcMain.handle("desktop-pet:get-model-config", () => {
    const config = loadModelConfig();
    return {
      activeModelId: config.activeModelId,
      models: config.models.map((item) => ({
        id: item.id,
        name: item.name,
        sessionId: item.sessionId,
        source: item.source,
        deletable: item.source !== "builtin",
        offsetX: item.offsetX ?? 0,
        offsetY: item.offsetY ?? 0,
        userScale: item.userScale ?? 1,
        followCursor: item.followCursor ?? true,
        motionConfig: item.motionConfig ?? [],
        entry: item.entry,
        modelUrl: resolveModelUrl(item),
      })),
    };
  });

  // 获取聊天设置
  ipcMain.handle("desktop-pet:get-chat-settings", async () => {
    const settings = await ensureChatSettingsLoaded();
    return settings;
  });

  // 获取最新 AI 消息
  ipcMain.handle("desktop-pet:get-latest-ai-message", async (_event, sessionId?: string) => {
    const resolvedSessionId = sessionId || getActiveModelRecord().sessionId;
    return {
      sessionId: resolvedSessionId,
      latestAiMessage: await fetchLatestAiMessageBySessionId(resolvedSessionId),
    };
  });

  // 获取聊天历史
  ipcMain.handle(
    "desktop-pet:get-chat-history",
    async (_event, sessionId: string, start: number, limit: number) => {
      return await fetchChatHistoryPageBySessionId(sessionId, start, limit);
    }
  );

  // 获取最后 N 条聊天历史
  ipcMain.handle(
    "desktop-pet:get-chat-history-last-n",
    async (_event, sessionId: string, n: number) => {
      return await fetchChatHistoryLastN(sessionId, n);
    }
  );

  ipcMain.handle("desktop-pet:get-pending-interrupt", async (_event, sessionId: string) => {
    const res = await net.fetch(
      `${BACKEND_BASE_URL}/agent/pending-interrupt/${encodeURIComponent(sessionId)}`
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `读取待处理中断失败: ${res.status}`);
    }
    const result = await res.json() as {
      data?: import("./types.js").PendingInterruptResult;
    };
    return result.data ?? { pending: false };
  });

  // 更新聊天设置
  ipcMain.handle("desktop-pet:update-chat-settings", async (_event, payload: ChatSettingsData) => {
    return await updateChatSettings(payload);
  });

  // 获取可用工具
  ipcMain.handle("desktop-pet:get-available-tools", async () => {
    const tools = await fetchAvailableTools();
    return { tools };
  });

  // 获取可用插件
  ipcMain.handle("desktop-pet:get-available-plugins", async () => {
    const plugins = await fetchAvailablePlugins();
    return { plugins };
  });

  // 更新模型变换
  ipcMain.handle(
    "desktop-pet:update-model-transform",
    (_event, payload: ModelTransformPayload) => {
      const config = loadModelConfig();
      const target = config.models.find((item) => item.id === payload.modelId);
      if (!target) {
        throw new Error("Model not found");
      }

      if (typeof payload.offsetX === "number") {
        target.offsetX = payload.offsetX;
      }
      if (typeof payload.offsetY === "number") {
        target.offsetY = payload.offsetY;
      }
      if (typeof payload.userScale === "number") {
        target.userScale = payload.userScale;
      }
      if (typeof payload.followCursor === "boolean") {
        target.followCursor = payload.followCursor;
      }

      saveModelConfig(config);
      notifyModelTransformChanged(target);

      return {
        modelId: target.id,
        offsetX: target.offsetX ?? 0,
        offsetY: target.offsetY ?? 0,
        userScale: target.userScale ?? 1,
        followCursor: target.followCursor ?? true,
      };
    }
  );

  // 预览 Live2D 导入
  ipcMain.handle("desktop-pet:preview-live2d-import", async () => {
    const chooser = getSettingsWindow() ?? getMainWindow();
    if (!chooser) {
      return null;
    }

    const result = await dialog.showOpenDialog(chooser, {
      title: "选择 Live2D 模型文件夹",
      properties: ["openDirectory"],
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return inspectImportSource(result.filePaths[0]);
  });

  // 导入 Live2D 模型
  ipcMain.handle(
    "desktop-pet:import-live2d-model",
    async (_event, payload?: { selectedPath: string; suggestedName?: string }) => {
      if (!payload?.selectedPath) {
        throw new Error("Missing import path");
      }

      const preview = inspectImportSource(payload.selectedPath);
      const modelName = sanitizeModelName(payload.suggestedName || preview.suggestedName);
      const destDir = resolveUniqueModelDir(modelName);

      copyDirectory(preview.selectedPath, destDir);

      const entryName = findModel3JsonRelativePath(destDir);
      if (!entryName) {
        fs.rmSync(destDir, { recursive: true, force: true });
        throw new Error("Model3.json not found in the selected folder");
      }

      const record = createModelRecord(modelName, destDir, entryName);

      try {
        await createEmptyChatSettings(record.sessionId);
      } catch (error) {
        fs.rmSync(destDir, { recursive: true, force: true });
        throw error;
      }

      const config = loadModelConfig();
      config.models.push(record);
      config.activeModelId = record.id;
      saveModelConfig(config);

      // 清除聊天设置缓存，确保下次获取新模型的设置
      clearChatSettingsCache();

      notifyModelChanged();

      return {
        id: record.id,
        name: record.name,
        sessionId: record.sessionId,
        source: record.source,
      };
    }
  );

  // 删除模型
  ipcMain.handle("desktop-pet:delete-model", async (_event, modelId: string) => {
    const config = loadModelConfig();
    const target = config.models.find((item) => item.id === modelId);
    if (!target) {
      throw new Error("Model not found");
    }

    if (target.source === "builtin") {
      throw new Error("Default model cannot be deleted");
    }

    await deleteChatSettingsBySessionId(target.sessionId);

    if (target.rootDir) {
      fs.rmSync(resolveRootDirAbsolute(target.rootDir), { recursive: true, force: true });
    }

    config.models = config.models.filter((item) => item.id !== modelId);
    if (config.models.length === 0) {
      const { createDefaultModelConfig } = await import("./model-manager.js");
      const fallback = createDefaultModelConfig();
      saveModelConfig(fallback);
      clearChatSettingsCache();
      notifyModelChanged();
      return {
        activeModelId: fallback.activeModelId,
      };
    }

    if (config.activeModelId === modelId) {
      const builtin =
        config.models.find((item) => item.id === "builtin-hiyori") ??
        config.models.find((item) => item.source === "builtin") ??
        config.models[0];
      config.activeModelId = builtin.id;
    }

    saveModelConfig(config);
    clearChatSettingsCache();
    notifyModelChanged();

    return {
      activeModelId: config.activeModelId,
    };
  });

  // 设置激活模型
  ipcMain.handle("desktop-pet:set-active-model", (_event, modelId: string) => {
    const config = loadModelConfig();
    if (!config.models.some((item) => item.id === modelId)) {
      throw new Error("Model not found");
    }

    config.activeModelId = modelId;
    saveModelConfig(config);

    // 清除聊天设置缓存
    clearChatSettingsCache();

    notifyModelChanged();

    return {
      activeModelId: config.activeModelId,
    };
  });

  // 打开设置窗口
  ipcMain.on("desktop-pet:open-settings-window", () => {
    openSettingsWindow();
  });

  // 最小化当前窗口
  ipcMain.on("desktop-pet:minimize-current-window", (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    win?.minimize();
  });

  // 关闭当前窗口
  ipcMain.on("desktop-pet:close-current-window", (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    win?.close();
  });

  // 打开图片预览窗口
  ipcMain.on("desktop-pet:open-image-preview", (_event, imageSrc: string) => {
    openImagePreviewWindow(imageSrc);
  });

  // 选择图片
  ipcMain.handle("desktop-pet:select-images", async () => {
    const chooser = getMainWindow();
    if (!chooser) {
      return null;
    }

    const result = await dialog.showOpenDialog(chooser, {
      title: "选择图片",
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "图片", extensions: ["jpg", "jpeg", "png", "gif", "bmp", "webp"] }],
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    // 读取文件并返回 data URL
    const images: Array<{ path: string; dataUrl: string }> = [];
    for (const filePath of result.filePaths) {
      try {
        const buffer = fs.readFileSync(filePath);
        const base64 = buffer.toString("base64");
        const ext = path.extname(filePath).toLowerCase().slice(1);
        const mimeType = ext === "jpg" ? "jpeg" : ext;
        images.push({
          path: filePath,
          dataUrl: `data:image/${mimeType};base64,${base64}`,
        });
      } catch (error) {
        console.warn("Failed to read image:", filePath, error);
      }
    }

    return images;
  });

  // 聊天请求
  ipcMain.handle(
    "desktop-pet:chat",
    async (
      event,
      payload:
        | string
        | { message: string; sessionId?: string; requestId?: string; images?: string[] }
    ) => {
      const message = typeof payload === "string" ? payload : payload.message;
      const sessionId = typeof payload === "string" ? undefined : payload.sessionId;
      const requestId = typeof payload === "string" ? undefined : payload.requestId;
      const images = typeof payload === "string" ? undefined : payload.images;
      const body: { message: string; session_id?: string; images?: string[] } = { message };
      if (sessionId) {
        body.session_id = sessionId;
      }
      if (images && images.length > 0) {
        body.images = images;
      }
      const abortController = new AbortController();
      const timeoutTimer = setTimeout(() => {
        abortController.abort();
      }, CHAT_REQUEST_TIMEOUT_MS);

      try {
        const res = await net.fetch(`${BACKEND_BASE_URL}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(body),
          signal: abortController.signal,
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `请求失败: ${res.status}`);
        }

        return await streamBackendResponse(
          event,
          res,
          requestId,
          "聊天流返回错误事件",
        );
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (error instanceof Error && error.name === "AbortError") {
          throw new Error("Chat request timeout (900s), please try again later");
        }
        if (
          errorMessage.includes("UND_ERR_BODY_TIMEOUT") ||
          errorMessage.toLowerCase().includes("body timeout") ||
          errorMessage.toLowerCase().includes("terminated")
        ) {
          throw new Error("Chat request timeout (900s), please try again later");
        }
        throw error;
      } finally {
        clearTimeout(timeoutTimer);
      }
    }
  );

  // 截屏审批响应
  ipcMain.handle(
    "desktop-pet:screenshot-respond",
    async (
      event,
      payload: {
        sessionId: string;
        approved: boolean;
        requestId?: string;
        screenshotData?: string;
        width?: number;
        height?: number;
      }
    ) => {
      const { sessionId, approved, requestId, screenshotData, width, height } = payload;

      const abortController = new AbortController();
      const timeoutTimer = setTimeout(() => {
        abortController.abort();
      }, CHAT_REQUEST_TIMEOUT_MS);

      try {
        // 构建请求体
        const requestBody: Record<string, unknown> = {
          session_id: sessionId,
          approved,
        };
        // 如果允许且有截图数据，添加到请求体
        if (approved && screenshotData) {
          requestBody.screenshot_data = screenshotData;
          if (width !== undefined) requestBody.width = width;
          if (height !== undefined) requestBody.height = height;
        }

        const res = await net.fetch(`${BACKEND_BASE_URL}/screenshot/respond`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(requestBody),
          signal: abortController.signal,
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `请求失败: ${res.status}`);
        }

        return await streamBackendResponse(
          event,
          res,
          requestId,
          "截屏响应流返回错误事件",
        );
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (error instanceof Error && error.name === "AbortError") {
          throw new Error("Screenshot respond timeout (900s), please try again later");
        }
        throw error;
      } finally {
        clearTimeout(timeoutTimer);
      }
    }
  );

  // 屏幕控制工具响应
  ipcMain.handle(
    "desktop-pet:control-screen-respond",
    async (
      event,
      payload: {
        sessionId: string;
        approved?: boolean;
        requestId?: string;
        screenshotData?: string;
        width?: number;
        height?: number;
        executed?: boolean;
        error?: string;
      }
    ) => {
      const { sessionId, approved, requestId, screenshotData, width, height, executed, error } = payload;

      const abortController = new AbortController();
      const timeoutTimer = setTimeout(() => {
        abortController.abort();
      }, CHAT_REQUEST_TIMEOUT_MS);

      try {
        const requestBody: Record<string, unknown> = {
          session_id: sessionId,
        };
        if (approved !== undefined) requestBody.approved = approved;
        if (screenshotData) requestBody.screenshot_data = screenshotData;
        if (width !== undefined) requestBody.width = width;
        if (height !== undefined) requestBody.height = height;
        if (executed !== undefined) requestBody.executed = executed;
        if (error) requestBody.error = error;

        const res = await net.fetch(`${BACKEND_BASE_URL}/control-screen/respond`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(requestBody),
          signal: abortController.signal,
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `请求失败: ${res.status}`);
        }

        return await streamBackendResponse(
          event,
          res,
          requestId,
          "屏幕控制响应流返回错误事件"
        );
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (error instanceof Error && error.name === "AbortError") {
          throw new Error("Control screen respond timeout (900s), please try again later");
        }
        throw new Error(errorMessage);
      } finally {
        clearTimeout(timeoutTimer);
      }
    }
  );

  // 执行屏幕控制动作
  ipcMain.handle(
    "desktop-pet:perform-screen-action",
    async (_event, payload: ScreenActionRequest): Promise<ScreenActionResult> => {
      return await performScreenAction(payload);
    }
  );

  // 截取屏幕
  ipcMain.handle("desktop-pet:capture-screen", async () => {
    console.log("[CaptureScreen] 开始截屏...");
    try {
      const sources = await desktopCapturer.getSources({
        types: ["screen"],
        thumbnailSize: { width: 1920, height: 1080 },
      });

      if (sources.length === 0) {
        throw new Error("未找到屏幕");
      }

      const primaryScreen = sources[0];
      const size = primaryScreen.thumbnail.getSize();
      const dataUrl = primaryScreen.thumbnail.toDataURL();

      console.log("[CaptureScreen] 截屏成功, 尺寸:", size.width, "x", size.height, ", 数据长度:", dataUrl.length);

      return {
        dataUrl,
        width: size.width,
        height: size.height,
      };
    } catch (error) {
      console.error("[CaptureScreen] 截屏失败:", error);
      throw error;
    }
  });

  // 获取前端设置
  ipcMain.handle("desktop-pet:get-frontend-settings", () => {
    const defaultSettings: FrontendSettings = {
      hide_on_screenshot: true,
    };

    try {
      if (!fs.existsSync(FRONTEND_SETTINGS_PATH)) {
        return defaultSettings;
      }
      const content = fs.readFileSync(FRONTEND_SETTINGS_PATH, "utf-8");
      const settings = JSON.parse(content) as Partial<FrontendSettings>;
      return { ...defaultSettings, ...settings };
    } catch {
      return defaultSettings;
    }
  });

  // 更新前端设置
  ipcMain.handle("desktop-pet:update-frontend-settings", (_event, settings: Partial<FrontendSettings>) => {
    let current: FrontendSettings;
    try {
      if (fs.existsSync(FRONTEND_SETTINGS_PATH)) {
        const content = fs.readFileSync(FRONTEND_SETTINGS_PATH, "utf-8");
        current = JSON.parse(content) as FrontendSettings;
      } else {
        current = { hide_on_screenshot: true };
      }
    } catch {
      current = { hide_on_screenshot: true };
    }

    const updated = { ...current, ...settings };
    fs.mkdirSync(path.dirname(FRONTEND_SETTINGS_PATH), { recursive: true });
    fs.writeFileSync(FRONTEND_SETTINGS_PATH, JSON.stringify(updated, null, 2), "utf-8");
    return updated;
  });

  // 获取模型动作配置
  ipcMain.handle("desktop-pet:get-motion-config", (_event, modelId: string) => {
    const config = loadModelConfig();
    const model = config.models.find((item) => item.id === modelId);
    return model?.motionConfig ?? [];
  });

  // 更新模型动作配置
  ipcMain.handle(
    "desktop-pet:update-model-motion-config",
    (_event, payload: { modelId: string; motionConfig: import("./types.js").MotionConfig[] }) => {
      const config = loadModelConfig();
      const target = config.models.find((item) => item.id === payload.modelId);
      if (!target) {
        throw new Error("Model not found");
      }

      target.motionConfig = payload.motionConfig;
      saveModelConfig(config);

      // 通知主窗口动作配置已更新
      const mainWindow = getMainWindow();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("desktop-pet:motion-config-changed", {
          modelId: payload.modelId,
          motionConfig: payload.motionConfig,
        });
      }
    }
  );

  // 播放动作（转发到主窗口）
  ipcMain.on("desktop-pet:play-motion", (_event, motionName: string) => {
    const mainWindow = getMainWindow();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("desktop-pet:play-motion-request", motionName);
    }
  });
};

/**
 * 清理聊天设置缓存的辅助函数
 */
export { clearChatSettingsCache };
