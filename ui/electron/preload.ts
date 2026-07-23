import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

import type {
  ChatChunkData,
  DesktopPetApi,
  ModelInfo,
  ModelTransformData,
  MotionConfig,
  ScreenshotInterruptPayload,
  ToolCallEventData,
} from "../shared-types.js";

const subscribe = <T>(channel: string, listener: (payload: T) => void): (() => void) => {
  const handler = (_event: IpcRendererEvent, payload: T): void => listener(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};

const desktopPetApi: DesktopPetApi = {
  chat: (message, sessionId, requestId, images) =>
    ipcRenderer.invoke("desktop-pet:chat", { message, sessionId, requestId, images }),
  selectImages: () => ipcRenderer.invoke("desktop-pet:select-images"),
  setMousePassthrough: (enabled) => {
    ipcRenderer.send("desktop-pet:set-mouse-passthrough", Boolean(enabled));
  },
  setPointerInteractive: (enabled) => {
    ipcRenderer.send("desktop-pet:set-pointer-interactive", Boolean(enabled));
  },
  openSettingsWindow: () => {
    ipcRenderer.send("desktop-pet:open-settings-window");
  },
  minimizeCurrentWindow: () => {
    ipcRenderer.send("desktop-pet:minimize-current-window");
  },
  closeCurrentWindow: () => {
    ipcRenderer.send("desktop-pet:close-current-window");
  },
  openImagePreview: (imageSrc) => {
    ipcRenderer.send("desktop-pet:open-image-preview", imageSrc);
  },
  getActiveModel: () => ipcRenderer.invoke("desktop-pet:get-active-model"),
  getModelConfig: () => ipcRenderer.invoke("desktop-pet:get-model-config"),
  getChatSettings: () => ipcRenderer.invoke("desktop-pet:get-chat-settings"),
  getLatestAiMessage: (sessionId) =>
    ipcRenderer.invoke("desktop-pet:get-latest-ai-message", sessionId),
  getChatHistory: (sessionId, start, limit) =>
    ipcRenderer.invoke("desktop-pet:get-chat-history", sessionId, start, limit),
  getChatHistoryLastN: (sessionId, n) =>
    ipcRenderer.invoke("desktop-pet:get-chat-history-last-n", sessionId, n),
  getPendingInterrupt: (sessionId) =>
    ipcRenderer.invoke("desktop-pet:get-pending-interrupt", sessionId),
  updateChatSettings: (payload) =>
    ipcRenderer.invoke("desktop-pet:update-chat-settings", payload),
  getAvailableTools: () => ipcRenderer.invoke("desktop-pet:get-available-tools"),
  getAvailablePlugins: () => ipcRenderer.invoke("desktop-pet:get-available-plugins"),
  getMcpServers: () => ipcRenderer.invoke("desktop-pet:get-mcp-servers"),
  testMcpServer: (config) => ipcRenderer.invoke("desktop-pet:test-mcp-server", config),
  createMcpServer: (config) => ipcRenderer.invoke("desktop-pet:create-mcp-server", config),
  updateMcpServer: (serverId, config) =>
    ipcRenderer.invoke("desktop-pet:update-mcp-server", serverId, config),
  deleteMcpServer: (serverId) => ipcRenderer.invoke("desktop-pet:delete-mcp-server", serverId),
  reconnectMcpServer: (serverId) =>
    ipcRenderer.invoke("desktop-pet:reconnect-mcp-server", serverId),
  getMcpServerTools: (serverId) =>
    ipcRenderer.invoke("desktop-pet:get-mcp-server-tools", serverId),
  previewLive2DImport: () => ipcRenderer.invoke("desktop-pet:preview-live2d-import"),
  importLive2DModel: (payload) =>
    ipcRenderer.invoke("desktop-pet:import-live2d-model", payload),
  updateModelTransform: (payload) =>
    ipcRenderer.invoke("desktop-pet:update-model-transform", payload),
  setActiveModel: (modelId) => ipcRenderer.invoke("desktop-pet:set-active-model", modelId),
  deleteModel: (modelId) => ipcRenderer.invoke("desktop-pet:delete-model", modelId),
  onCursor: (listener) => subscribe("desktop-pet:cursor", listener),
  onModelChanged: (listener) =>
    subscribe<ModelInfo>("desktop-pet:model-changed", listener),
  onModelTransformChanged: (listener) =>
    subscribe<ModelTransformData>("desktop-pet:model-transform-changed", listener),
  onChatChunk: (listener) =>
    subscribe<ChatChunkData>("desktop-pet:chat-chunk", listener),
  screenshotRespond: (payload) =>
    ipcRenderer.invoke("desktop-pet:screenshot-respond", payload),
  controlScreenRespond: (payload) =>
    ipcRenderer.invoke("desktop-pet:control-screen-respond", payload),
  mcpToolRespond: (payload) => ipcRenderer.invoke("desktop-pet:mcp-tool-respond", payload),
  captureScreen: () => ipcRenderer.invoke("desktop-pet:capture-screen"),
  performScreenAction: (payload) =>
    ipcRenderer.invoke("desktop-pet:perform-screen-action", payload),
  onChatInterrupt: (listener) =>
    subscribe<ScreenshotInterruptPayload>("desktop-pet:chat-interrupt", listener),
  onToolCall: (listener) =>
    subscribe<ToolCallEventData>("desktop-pet:chat-tool-call", listener),
  getFrontendSettings: () => ipcRenderer.invoke("desktop-pet:get-frontend-settings"),
  updateFrontendSettings: (settings) =>
    ipcRenderer.invoke("desktop-pet:update-frontend-settings", settings),
  getMotionConfig: (modelId) =>
    ipcRenderer.invoke("desktop-pet:get-motion-config", modelId),
  updateModelMotionConfig: (payload) =>
    ipcRenderer.invoke("desktop-pet:update-model-motion-config", payload),
  playMotion: (motionName) => {
    ipcRenderer.send("desktop-pet:play-motion", motionName);
  },
  onPlayMotionRequest: (listener) =>
    subscribe<string>("desktop-pet:play-motion-request", listener),
  onMotionConfigChanged: (listener) =>
    subscribe<{ modelId: string; motionConfig: MotionConfig[] }>(
      "desktop-pet:motion-config-changed",
      listener
    ),
};

contextBridge.exposeInMainWorld("desktopPetApi", desktopPetApi);
