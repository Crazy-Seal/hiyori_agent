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
  mcp: MCPModelSettings;
  context_strategy: ContextStrategyConfig;
  agent_plugins?: Record<string, AgentPluginSettings> | null;
  name?: string | null;
  feature?: string | null;
  character?: string | null;
  address?: string | null;
  characteristic?: string | null;
  constraint?: string | null;
};

export type MCPToolPolicy = "allow" | "ask" | "deny";

export type MCPModelSettings = {
  servers: Record<string, {
    enabled: boolean;
    tools: Record<string, MCPToolPolicy>;
    identity_fingerprint?: string | null;
  }>;
};

export type MCPServerStatus = "disabled" | "disconnected" | "connecting" | "available" | "error";

export type MCPStdioServerConfig = {
  id: string;
  name: string;
  enabled: boolean;
  transport: "stdio";
  connect_timeout_seconds: number;
  call_timeout_seconds: number;
  command: string;
  args: string[];
  cwd?: string | null;
  env: Record<string, string>;
};

export type MCPHttpServerConfig = {
  id: string;
  name: string;
  enabled: boolean;
  transport: "streamable_http";
  connect_timeout_seconds: number;
  call_timeout_seconds: number;
  url: string;
  headers: Record<string, string>;
};

export type MCPServerConfig = MCPStdioServerConfig | MCPHttpServerConfig;

export type MCPToolInfo = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
};

export type MCPServerView = {
  config: MCPServerConfig;
  affected_model_count: number;
  runtime: {
    status: MCPServerStatus;
    tool_count: number;
    last_error: string | null;
    instructions: string | null;
  };
};

export type MCPTestResult = {
  status: "available";
  instructions: string | null;
  tools: MCPToolInfo[];
};

export type ContextStrategyConfig = {
  recent_context_human_messages: number;
  max_images_in_context: number;
  image_ttl_human_messages: number;
  max_screenshots_in_context: number;
  screenshot_ttl_human_messages: number;
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
  id?: string;
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

export type ScreenshotInterruptData = {
  type: "screenshot_request";
  request_id: string;
  message: string;
};

export type ControlScreenOperation = "click" | "double" | "right" | "scroll";
export type ControlScreenScrollDirection = "none" | "down" | "up";

export type ControlScreenCoordinates = {
  bbox: [number, number, number, number];
  x_ratio: number;
  y_ratio: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type ControlScreenActionData = {
  target: string;
  operation: ControlScreenOperation;
  text: string;
  press_enter: boolean;
  wait_seconds: number;
  scroll_direction: ControlScreenScrollDirection;
  coordinates: ControlScreenCoordinates;
};

export type ControlScreenCaptureInterruptData = {
  type: "control_screen_capture_request";
  request_id: string;
  message: string;
};

export type ControlScreenExecuteInterruptData = {
  type: "control_screen_execute_request";
  request_id: string;
  message: string;
  data: ControlScreenActionData;
};

export type MCPToolApprovalInterruptData = {
  type: "mcp_tool_approval_request";
  request_id: string;
  message: string;
  data: {
    server_id: string;
    server_name: string;
    tool_name: string;
    description: string;
    arguments: Record<string, unknown>;
  };
};

export type ChatInterruptData =
  | ScreenshotInterruptData
  | ControlScreenCaptureInterruptData
  | ControlScreenExecuteInterruptData
  | MCPToolApprovalInterruptData;

export type ChatInterruptPayload = {
  value: ChatInterruptData;
};

export type PendingInterruptResult =
  | { pending: false }
  | { pending: true; interrupt: ChatInterruptPayload };

export type ScreenshotInterruptPayload = ChatInterruptPayload;

export type ScreenshotResponsePayload = {
  sessionId: string;
  requestId: string;
  streamRequestId?: string;
  approved: boolean;
  screenshotData?: string;
  width?: number;
  height?: number;
};

export type ControlScreenResponsePayload = {
  sessionId: string;
  requestId: string;
  streamRequestId?: string;
  approved?: boolean;
  screenshotData?: string;
  width?: number;
  height?: number;
  executed?: boolean;
  error?: string;
};

export type ChatResult =
  | { response: string; model: string; interrupted?: false }
  | {
      interrupted: true;
      interruptData: ChatInterruptPayload;
      response: string;
      model: string;
    };

export type ToolCallEventData = {
  requestId: string;
  toolName: string;
};

export type FrontendSettings = {
  hide_on_screenshot: boolean;
};

export type ScreenActionRequest = ControlScreenActionData;

export type ScreenActionResult = {
  executed: boolean;
  error?: string;
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
  getPendingInterrupt: (sessionId: string) => Promise<PendingInterruptResult>;
  updateChatSettings: (settings: ChatSettingsData) => Promise<ChatSettingsData>;
  getAvailableTools: () => Promise<{ tools: ToolItem[] }>;
  getAvailablePlugins: () => Promise<{ plugins: PluginItem[] }>;
  getMcpServers: () => Promise<MCPServerView[]>;
  testMcpServer: (config: MCPServerConfig) => Promise<MCPTestResult>;
  createMcpServer: (config: MCPServerConfig) => Promise<MCPServerView>;
  updateMcpServer: (serverId: string, config: MCPServerConfig) => Promise<MCPServerView>;
  deleteMcpServer: (serverId: string) => Promise<{ affected_sessions: string[] }>;
  reconnectMcpServer: (serverId: string) => Promise<MCPServerView>;
  getMcpServerTools: (serverId: string) => Promise<MCPToolInfo[]>;
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
  screenshotRespond?: (payload: ScreenshotResponsePayload) => Promise<ChatResult>;
  controlScreenRespond?: (payload: ControlScreenResponsePayload) => Promise<ChatResult>;
  mcpToolRespond?: (payload: {
    sessionId: string;
    requestId: string;
    streamRequestId?: string;
    approved: boolean;
  }) => Promise<ChatResult>;
  captureScreen?: () => Promise<{ dataUrl: string; width: number; height: number }>;
  performScreenAction?: (payload: ScreenActionRequest) => Promise<ScreenActionResult>;
  onChatInterrupt?: (callback: (data: ChatInterruptPayload) => void) => () => void;
  onToolCall?: (callback: (data: ToolCallEventData) => void) => () => void;
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
