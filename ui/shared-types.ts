/**
 * 共享类型定义
 * 供主进程、主窗口、设置窗口共同使用
 */

/**
 * 动作设置类型
 */
export type MotionSettingType = 'idle' | 'expression' | 'none';

/**
 * 动作配置
 */
export type MotionConfig = {
  motionName: string;
  setting: MotionSettingType;
  label?: string;
};

export type ModelInfo = {
  id: string;
  name: string;
  sessionId: string;
  modelUrl: string;
  offsetX: number;
  offsetY: number;
  userScale: number;
  followCursor: boolean;
  motionConfig?: MotionConfig[];
  entry?: string;
};

export type ModelConfigView = {
  activeModelId: string;
  models: Array<{
    id: string;
    name: string;
    sessionId: string;
    source: "builtin" | "custom";
    deletable: boolean;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
    motionConfig?: MotionConfig[];
    entry?: string;
    modelUrl?: string;
  }>;
};

export type ChatSettingsData = {
  session_id: string;
  model_name: string;
  openai_api_key: string;
  openai_base_url: string;
  temperature: number;
  system_prompt: string;
  tools_list: string[];
  agent_plugins?: Record<string, AgentPluginSettings> | null;
  name?: string | null;
  feature?: string | null;
  character?: string | null;
  address?: string | null;
  characteristic?: string | null;
  constraint?: string | null;
};

export type AgentPluginSettings = {
  enabled: boolean;
  config: Record<string, unknown>;
};

export type PluginItem = {
  name: string;
  description: string;
  inherent: boolean;
  default_config: Record<string, unknown>;
  config_schema: Record<string, unknown>;
};

export type ToolItem = {
  name: string;
  description: string;
};

export type ChatHistoryItem = {
  role: string;
  content: string;
  timestamp: string;
  images?: string[];
};

export type ApiResponse<T> = {
  data?: T;
  msg?: string;
  code?: number;
};

export type ModelTransformData = {
  id: string;
  offsetX: number;
  offsetY: number;
  userScale: number;
  followCursor: boolean;
};

export type CursorSyncData = {
  localX: number;
  localY: number;
  screenX: number;
  screenY: number;
  windowX: number;
  windowY: number;
  windowWidth: number;
  windowHeight: number;
  displayX: number;
  displayY: number;
  displayWidth: number;
  displayHeight: number;
  insideWindow: boolean;
};

export type ChatChunkData = {
  requestId: string;
  chunk: string;
  aggregated: string;
};

export type ScreenshotInterruptPayload = {
  value: {
    type: "screenshot_request";
    request_id: string;
    message: string;
  };
};

export type ChatResult =
  | { response: string; model: string; interrupted?: false }
  | {
      interrupted: true;
      interruptData: ScreenshotInterruptPayload;
      response: string;
      model: string;
    };

export type ToolCallEventData = {
  requestId: string;
  toolName: string;
};

export type AgentErrorEventData = {
  requestId: string;
  errorMessage: string;
};

export type FrontendSettings = {
  hide_on_screenshot: boolean;
};

export type ImportPreview = {
  selectedPath: string;
  sourceType: "directory";
  suggestedName: string;
  entryRelativePath: string;
};

export interface DesktopPetApi {
  chat: (
    message: string,
    sessionId?: string,
    requestId?: string,
    images?: string[]
  ) => Promise<ChatResult>;
  selectImages: () => Promise<Array<{ path: string; dataUrl: string }> | null>;
  setMousePassthrough: (enabled: boolean) => void;
  setPointerInteractive: (enabled: boolean) => void;
  openSettingsWindow: () => void;
  minimizeCurrentWindow: () => void;
  closeCurrentWindow: () => void;
  openImagePreview: (imageSrc: string) => void;
  getActiveModel: () => Promise<ModelInfo>;
  getModelConfig: () => Promise<ModelConfigView>;
  getChatSettings: () => Promise<ChatSettingsData>;
  getLatestAiMessage: (sessionId?: string) => Promise<{
    sessionId: string;
    latestAiMessage: string | null;
  }>;
  getChatHistory: (sessionId: string, start: number, limit: number) => Promise<ChatHistoryItem[]>;
  getChatHistoryLastN: (sessionId: string, n: number) => Promise<ChatHistoryItem[]>;
  updateChatSettings: (settings: ChatSettingsData) => Promise<ApiResponse<never>>;
  getAvailableTools: () => Promise<{ tools: ToolItem[] }>;
  getAvailablePlugins: () => Promise<{ plugins: PluginItem[] }>;
  previewLive2DImport: () => Promise<ImportPreview | null>;
  importLive2DModel: (payload: {
    selectedPath: string;
    suggestedName?: string;
  }) => Promise<{ id: string; name: string; sessionId: string; source: string }>;
  updateModelTransform: (payload: {
    modelId: string;
    offsetX?: number;
    offsetY?: number;
    userScale?: number;
    followCursor?: boolean;
  }) => Promise<{
    modelId: string;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }>;
  setActiveModel: (modelId: string) => Promise<{ activeModelId: string }>;
  deleteModel: (modelId: string) => Promise<{ activeModelId: string }>;
  onCursor?: (callback: (data: CursorSyncData) => void) => () => void;
  onModelChanged?: (callback: (model: ModelInfo) => void) => () => void;
  onModelTransformChanged?: (callback: (data: ModelTransformData) => void) => () => void;
  onChatChunk: (callback: (data: ChatChunkData) => void) => () => void;
  screenshotRespond?: (
    sessionId: string,
    approved: boolean,
    requestId?: string,
    screenshotData?: string,
    width?: number,
    height?: number
  ) => Promise<ChatResult>;
  captureScreen?: () => Promise<{ dataUrl: string; width: number; height: number }>;
  onChatInterrupt?: (callback: (data: ScreenshotInterruptPayload) => void) => () => void;
  onToolCall?: (callback: (data: ToolCallEventData) => void) => () => void;
  onChatAgentError?: (callback: (data: AgentErrorEventData) => void) => () => void;
  getFrontendSettings: () => Promise<FrontendSettings>;
  updateFrontendSettings: (settings: Partial<FrontendSettings>) => Promise<FrontendSettings>;
  getMotionConfig: (modelId: string) => Promise<MotionConfig[]>;
  updateModelMotionConfig: (payload: { modelId: string; motionConfig: MotionConfig[] }) => Promise<void>;
  playMotion: (motionName: string) => void;
  onPlayMotionRequest?: (callback: (motionName: string) => void) => () => void;
  onMotionConfigChanged?: (
    callback: (payload: { modelId: string; motionConfig: MotionConfig[] }) => void
  ) => () => void;
}
