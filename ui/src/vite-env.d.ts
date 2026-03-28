interface DesktopPetApi {
  chat: (message: string, sessionId?: string, requestId?: string) => Promise<{ response: string; model: string }>;
  setMousePassthrough: (enabled: boolean) => void;
  setPointerInteractive: (enabled: boolean) => void;
  openSettingsWindow: () => void;
  minimizeCurrentWindow: () => void;
  closeCurrentWindow: () => void;
  getActiveModel: () => Promise<{
    id: string;
    name: string;
    sessionId: string;
    modelUrl: string;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }>;
  getModelConfig: () => Promise<{
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
    }>;
  }>;
  getChatSettings: () => Promise<{
    session_id: string;
    model_name: string;
    openai_api_key: string;
    openai_base_url: string;
    temperature: number;
    system_prompt: string;
    tools_list: string[];
  }>;
  getLatestAiMessage: (sessionId?: string) => Promise<{
    sessionId: string;
    latestAiMessage: string | null;
  }>;
  updateChatSettings: (payload: {
    session_id: string;
    model_name: string;
    openai_api_key: string;
    openai_base_url: string;
    temperature: number;
    system_prompt: string;
    tools_list: string[];
  }) => Promise<{
    data: null;
    msg: string;
    code: number;
  }>;
  getAvailableTools: () => Promise<{
    tools: Array<{
      name: string;
    }>;
  }>;
  previewLive2DImport: () => Promise<{
    selectedPath: string;
    sourceType: "directory";
    suggestedName: string;
    entryRelativePath: string;
  } | null>;
  importLive2DModel: (payload: { selectedPath: string; suggestedName?: string }) => Promise<{
    id: string;
    name: string;
    sessionId: string;
    source: "builtin" | "custom";
  } | null>;
  setActiveModel: (modelId: string) => Promise<{ activeModelId: string }>;
  updateModelTransform: (payload: { modelId: string; offsetX?: number; offsetY?: number; userScale?: number; followCursor?: boolean }) => Promise<{
    modelId: string;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }>;
  deleteModel: (modelId: string) => Promise<{ activeModelId: string }>;
  onCursor: (listener: (payload: {
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
  }) => void) => () => void;
  onModelChanged: (listener: (payload: {
    id: string;
    name: string;
    sessionId: string;
    modelUrl: string;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }) => void) => () => void;
  onModelTransformChanged: (listener: (payload: {
    id: string;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }) => void) => () => void;
  onChatChunk: (listener: (payload: {
    requestId: string;
    chunk: string;
    aggregated: string;
  }) => void) => () => void;
}

declare global {
  interface Window {
    desktopPetApi: DesktopPetApi;
  }
}

export {};
