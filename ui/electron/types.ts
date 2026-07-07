/**
 * Electron 主进程类型定义。
 * IPC 边界 DTO 统一从 shared-types 导入，避免与 renderer 漂移。
 */
import type {
  ApiResponse as SharedApiResponse,
  ChatChunkData,
  ChatHistoryItem as SharedChatHistoryItem,
  ChatResult as SharedChatResult,
  ChatSettingsData as SharedChatSettingsData,
  CursorSyncData,
  FrontendSettings as SharedFrontendSettings,
  ImportPreview as SharedImportPreview,
  ModelInfo,
  ModelTransformData,
  MotionConfig as SharedMotionConfig,
  MotionSettingType as SharedMotionSettingType,
  PluginItem as SharedPluginItem,
  ScreenshotInterruptPayload as SharedScreenshotInterruptPayload,
  ToolCallEventData,
  ToolItem as SharedToolItem,
} from "../shared-types.js";

export type MotionConfig = SharedMotionConfig;
export type MotionSettingType = SharedMotionSettingType;
export type ToolItem = SharedToolItem;
export type PluginItem = SharedPluginItem;
export type ChatSettingsData = SharedChatSettingsData;
export type ChatHistoryItem = SharedChatHistoryItem;
export type ApiResponse<T> = SharedApiResponse<T>;
export type CursorSyncPayload = CursorSyncData;
export type ModelChangedPayload = ModelInfo;
export type ModelTransformChangedPayload = ModelTransformData;
export type ChatChunkPayload = ChatChunkData;
export type ScreenshotInterruptPayload = SharedScreenshotInterruptPayload;
export type ScreenshotInterruptData = SharedScreenshotInterruptPayload["value"];
export type ChatResult = SharedChatResult;
export type ToolCallEventPayload = ToolCallEventData;
export type FrontendSettings = SharedFrontendSettings;
export type ImportPreview = SharedImportPreview;

export type ModelSource = "builtin" | "custom";

export type ModelRecord = {
  id: string;
  name: string;
  sessionId: string;
  source: ModelSource;
  entry: string;
  rootDir?: string;
  offsetX?: number;
  offsetY?: number;
  userScale?: number;
  followCursor?: boolean;
  motionConfig?: MotionConfig[];
};

export type ModelConfig = {
  activeModelId: string;
  models: ModelRecord[];
};

export type ModelTransformPayload = {
  modelId: string;
  offsetX?: number;
  offsetY?: number;
  userScale?: number;
  followCursor?: boolean;
};

/** 后端 SSE tool_call 事件的原始载荷。 */
export type ToolCallPayload = {
  tool_name: string;
};
