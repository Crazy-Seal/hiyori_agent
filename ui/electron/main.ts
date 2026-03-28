import { app, BrowserWindow, dialog, ipcMain, net, protocol, screen } from "electron";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const WINDOW_WIDTH = 460;
const WINDOW_HEIGHT = 760;
const SETTINGS_WIDTH = 820;
const SETTINGS_HEIGHT = 520;
const CHAT_REQUEST_TIMEOUT_MS = 900_000;
const CHAT_HISTORY_PAGE_SIZE = 200;
const CHAT_HISTORY_MAX_PAGES = 500;
const backendBaseUrl = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";
const UI_ROOT = path.resolve(__dirname, "..");
const WORKSPACE_ROOT = path.resolve(UI_ROOT, "..");
const TOOLS_REGISTRY_FILE = path.join(WORKSPACE_ROOT, "app", "agent", "tools", "__init__.py");
const USER_DATA_DIR = path.join(UI_ROOT, "user_data");
const IMPORTED_MODELS_DIR = path.join(USER_DATA_DIR, "live2d_models");
const LEGACY_IMPORTED_MODELS_DIR = path.join(UI_ROOT, "dist", "live2d");
const MODEL_CONFIG_PATH = path.join(USER_DATA_DIR, "models.json");
let mainWindow: BrowserWindow | null = null;
let settingsWindow: BrowserWindow | null = null;
let cursorSyncTimer: NodeJS.Timeout | null = null;

type ModelRecord = {
  id: string;
  name: string;
  sessionId: string;
  source: "builtin" | "custom";
  entry: string;
  rootDir?: string;
  offsetX?: number;
  offsetY?: number;
  userScale?: number;
  followCursor?: boolean;
};

type ModelConfig = {
  activeModelId: string;
  models: ModelRecord[];
};

type ImportPreview = {
  selectedPath: string;
  sourceType: "directory";
  suggestedName: string;
  entryRelativePath: string;
};

type ToolItem = {
  name: string;
};

type ChatSettingsData = {
  session_id: string;
  model_name: string;
  openai_api_key: string;
  openai_base_url: string;
  temperature: number;
  system_prompt: string;
  tools_list: string[];
};

type ChatHistoryItem = {
  role: string;
  content: string;
  timestamp: string;
};

let chatSettingsCache: ChatSettingsData | null = null;

protocol.registerSchemesAsPrivileged([
  {
    scheme: "live2d",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true
    }
  }
]);

const ensureStorage = () => {
  fs.mkdirSync(USER_DATA_DIR, { recursive: true });
  fs.mkdirSync(IMPORTED_MODELS_DIR, { recursive: true });
};

const toPosixRelativeFrom = (baseDir: string, absolutePath: string): string => {
  return path.relative(baseDir, absolutePath).replaceAll("\\", "/");
};

const toPosixRelative = (absolutePath: string): string => {
  return path.relative(UI_ROOT, absolutePath).replaceAll("\\", "/");
};

const resolveRootDirAbsolute = (rootDir: string): string => {
  if (path.isAbsolute(rootDir)) {
    return rootDir;
  }

  const fromUserData = path.resolve(USER_DATA_DIR, rootDir);
  if (fs.existsSync(fromUserData)) {
    return fromUserData;
  }

  return path.resolve(UI_ROOT, rootDir);
};

const sanitizeModelName = (name: string): string => {
  const cleaned = name.trim().replace(/[\\/:*?"<>|]/g, "_");
  return cleaned || `model_${Date.now()}`;
};

const resolveUniqueModelDir = (baseName: string): string => {
  const normalized = sanitizeModelName(baseName);
  let candidate = path.join(IMPORTED_MODELS_DIR, normalized);
  let index = 1;
  while (fs.existsSync(candidate)) {
    candidate = path.join(IMPORTED_MODELS_DIR, `${normalized}_${index}`);
    index += 1;
  }
  return candidate;
};

const findModel3JsonRelativePath = (rootDir: string): string | null => {
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) {
      continue;
    }

    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolutePath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(absolutePath);
        continue;
      }

      if (entry.isFile() && entry.name.endsWith(".model3.json")) {
        return path.relative(rootDir, absolutePath).replaceAll("\\", "/");
      }
    }
  }

  return null;
};

const copyDirectory = (fromDir: string, toDir: string) => {
  fs.cpSync(fromDir, toDir, { recursive: true, force: true });
};

const inspectImportSource = (selectedPath: string): ImportPreview => {
  const stat = fs.statSync(selectedPath);
  if (stat.isDirectory()) {
    const entryRelativePath = findModel3JsonRelativePath(selectedPath);
    if (!entryRelativePath) {
      throw new Error("所选文件夹中未找到 .model3.json");
    }

    return {
      selectedPath,
      sourceType: "directory",
      suggestedName: sanitizeModelName(path.basename(selectedPath)),
      entryRelativePath
    };
  }

  throw new Error("请导入 Live2D 模型文件夹");
};

const loadAvailableTools = (): ToolItem[] => {
  if (!fs.existsSync(TOOLS_REGISTRY_FILE)) {
    return [];
  }

  const content = fs.readFileSync(TOOLS_REGISTRY_FILE, "utf-8");
  const blockMatch = content.match(/TOOLS_REGISTRY\s*=\s*\{([\s\S]*?)\}/m);
  if (!blockMatch) {
    return [];
  }

  const block = blockMatch[1];
  const keyPattern = /["']([^"']+)["']\s*:/g;
  const tools: ToolItem[] = [];
  const seen = new Set<string>();
  let matched: RegExpExecArray | null = keyPattern.exec(block);

  while (matched) {
    const name = matched[1].trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      tools.push({ name });
    }
    matched = keyPattern.exec(block);
  }

  return tools;
};

const createDefaultModelConfig = (): ModelConfig => {
  const builtinId = "builtin-hiyori";
  return {
    activeModelId: builtinId,
    models: [
      {
        id: builtinId,
        name: "hiyori_pro_t11",
        sessionId: randomUUID(),
        source: "builtin",
        entry: "/live2d/hiyori_pro_zh/runtime/hiyori_pro_t11.model3.json",
        offsetX: 0,
        offsetY: 0,
        userScale: 1,
        followCursor: true
      }
    ]
  };
};

const loadModelConfig = (): ModelConfig => {
  ensureStorage();
  if (!fs.existsSync(MODEL_CONFIG_PATH)) {
    const initial = createDefaultModelConfig();
    fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify(initial, null, 2), "utf-8");
    return initial;
  }

  try {
    const raw = fs.readFileSync(MODEL_CONFIG_PATH, "utf-8");
    const parsed = JSON.parse(raw) as ModelConfig;
    let changed = false;

    for (const model of parsed.models ?? []) {
      if (model.source === "custom" && model.rootDir) {
        if (path.isAbsolute(model.rootDir)) {
          model.rootDir = toPosixRelative(model.rootDir);
          changed = true;
        }

        const modelRootAbs = resolveRootDirAbsolute(model.rootDir);
        const normalizedLegacyBase = path.normalize(`${LEGACY_IMPORTED_MODELS_DIR}${path.sep}`);
        const normalizedModelRoot = path.normalize(modelRootAbs);
        if (normalizedModelRoot.startsWith(normalizedLegacyBase) && fs.existsSync(modelRootAbs)) {
          const targetRoot = resolveUniqueModelDir(path.basename(modelRootAbs));
          copyDirectory(modelRootAbs, targetRoot);
          model.rootDir = toPosixRelativeFrom(USER_DATA_DIR, targetRoot);
          changed = true;
        }
      }

      if (typeof model.offsetX !== "number") {
        model.offsetX = 0;
        changed = true;
      }
      if (typeof model.offsetY !== "number") {
        model.offsetY = 0;
        changed = true;
      }
      if (typeof model.userScale !== "number") {
        model.userScale = 1;
        changed = true;
      }
      if (typeof model.followCursor !== "boolean") {
        model.followCursor = true;
        changed = true;
      }
    }

    if (!Array.isArray(parsed.models) || parsed.models.length === 0) {
      const initial = createDefaultModelConfig();
      fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify(initial, null, 2), "utf-8");
      return initial;
    }

    if (!parsed.models.some((item) => item.id === parsed.activeModelId)) {
      parsed.activeModelId = parsed.models[0].id;
      changed = true;
    }

    if (changed) {
      fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify(parsed, null, 2), "utf-8");
    }

    return parsed;
  } catch {
    const initial = createDefaultModelConfig();
    fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify(initial, null, 2), "utf-8");
    return initial;
  }
};

const saveModelConfig = (config: ModelConfig) => {
  ensureStorage();
  fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify(config, null, 2), "utf-8");
};

const getActiveModelRecord = (): ModelRecord => {
  const config = loadModelConfig();
  const found = config.models.find((item) => item.id === config.activeModelId);
  return found ?? config.models[0];
};

const parseJsonSafe = async <T>(res: Response): Promise<T | null> => {
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
};

const fetchChatSettingsBySessionId = async (sessionId: string): Promise<ChatSettingsData> => {
  const url = `${backendBaseUrl}/chat_settings/${encodeURIComponent(sessionId)}`;
  const res = await fetch(url, {
    method: "GET"
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `读取 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<{
    data?: Partial<ChatSettingsData> | null;
    msg?: string;
    code?: number;
  }>(res);

  if (!result || result.code !== 200 || !result.data) {
    throw new Error(result?.msg || "读取 chat_settings 失败：返回格式错误");
  }

  return {
    session_id: String(result.data.session_id ?? sessionId),
    model_name: String(result.data.model_name ?? ""),
    openai_api_key: String(result.data.openai_api_key ?? ""),
    openai_base_url: String(result.data.openai_base_url ?? ""),
    temperature: typeof result.data.temperature === "number" ? result.data.temperature : 0.7,
    system_prompt: String(result.data.system_prompt ?? ""),
    tools_list: Array.isArray(result.data.tools_list)
      ? result.data.tools_list.map((item) => String(item))
      : []
  };
};

const fetchChatHistoryPageBySessionId = async (
  sessionId: string,
  start: number,
  limit: number
): Promise<ChatHistoryItem[]> => {
  const url = `${backendBaseUrl}/chat_history/${encodeURIComponent(sessionId)}?start=${start}&limit=${limit}`;
  const res = await fetch(url, {
    method: "GET"
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `读取 chat_history 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<{
    data?: Array<Partial<ChatHistoryItem>>;
    msg?: string;
    code?: number;
  }>(res);

  if (!result || result.code !== 200 || !Array.isArray(result.data)) {
    throw new Error(result?.msg || "读取 chat_history 失败：返回格式错误");
  }

  return result.data.map((item) => ({
    role: String(item.role ?? ""),
    content: String(item.content ?? ""),
    timestamp: String(item.timestamp ?? "")
  }));
};

const fetchLatestAiMessageBySessionId = async (sessionId: string): Promise<string | null> => {
  let start = 0;
  let pageCount = 0;
  let latestAiMessage: string | null = null;

  while (pageCount < CHAT_HISTORY_MAX_PAGES) {
    const historyPage = await fetchChatHistoryPageBySessionId(sessionId, start, CHAT_HISTORY_PAGE_SIZE);
    if (historyPage.length === 0) {
      break;
    }

    const pageLatestAi = getLatestAiMessageFromHistory(historyPage);
    if (pageLatestAi) {
      latestAiMessage = pageLatestAi;
    }

    if (historyPage.length < CHAT_HISTORY_PAGE_SIZE) {
      break;
    }

    start += CHAT_HISTORY_PAGE_SIZE;
    pageCount += 1;
  }

  return latestAiMessage;
};

const getLatestAiMessageFromHistory = (history: ChatHistoryItem[]): string | null => {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = history[index];
    const role = item.role.trim().toLowerCase();
    const isAi = role === "ai" || role === "assistant";
    const content = item.content.trim();
    if (isAi && content.length > 0) {
      return content;
    }
  }

  return null;
};

const createEmptyChatSettings = async (sessionId: string) => {
  const payload: ChatSettingsData = {
    session_id: sessionId,
    model_name: "",
    openai_api_key: "",
    openai_base_url: "",
    temperature: 0,
    system_prompt: "",
    tools_list: []
  };

  const res = await fetch(`${backendBaseUrl}/chat_settings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `创建 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<{ msg?: string; code?: number }>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "创建 chat_settings 失败：返回格式错误");
  }
};

const deleteChatSettingsBySessionId = async (sessionId: string) => {
  const url = `${backendBaseUrl}/chat_settings/${encodeURIComponent(sessionId)}`;
  const res = await fetch(url, {
    method: "DELETE"
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `删除 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<{ msg?: string; code?: number }>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "删除 chat_settings 失败：返回格式错误");
  }
};

const ensureChatSettingsLoaded = async () => {
  const active = getActiveModelRecord();
  if (chatSettingsCache && chatSettingsCache.session_id === active.sessionId) {
    return chatSettingsCache;
  }

  const fetched = await fetchChatSettingsBySessionId(active.sessionId);
  chatSettingsCache = fetched;
  return fetched;
};

const resolveModelUrl = (model: ModelRecord): string => {
  if (model.source === "builtin") {
    return model.entry;
  }

  const encodedEntry = model.entry
    .replaceAll("\\", "/")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `live2d://${model.id}/${encodedEntry}`;
};

const notifyModelChanged = () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const active = getActiveModelRecord();
  mainWindow.webContents.send("desktop-pet:model-changed", {
    id: active.id,
    name: active.name,
    sessionId: active.sessionId,
    modelUrl: resolveModelUrl(active),
    offsetX: active.offsetX ?? 0,
    offsetY: active.offsetY ?? 0,
    userScale: active.userScale ?? 1,
    followCursor: active.followCursor ?? true
  });
};

const notifyModelTransformChanged = (model: ModelRecord) => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  mainWindow.webContents.send("desktop-pet:model-transform-changed", {
    id: model.id,
    offsetX: model.offsetX ?? 0,
    offsetY: model.offsetY ?? 0,
    userScale: model.userScale ?? 1,
    followCursor: model.followCursor ?? true
  });
};

const createWindow = () => {
  const display = screen.getPrimaryDisplay();
  const { x, y, width, height } = display.workArea;
  const windowX = x + width - WINDOW_WIDTH - 20;
  const windowY = y + height - WINDOW_HEIGHT - 20;

  const win = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    x: windowX,
    y: windowY,
    frame: false,
    transparent: true,
    resizable: false,
    hasShadow: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    fullscreenable: false,
    webPreferences: {
      preload: path.resolve(__dirname, "../electron/preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true });
  mainWindow = win;

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    win.loadURL(devServerUrl);
  } else {
    win.loadFile(path.resolve(__dirname, "../dist/index.html"));
  }
};

const openSettingsWindow = () => {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.focus();
    return;
  }

  const parentBounds = mainWindow?.getBounds();
  const x = parentBounds ? Math.max(parentBounds.x - SETTINGS_WIDTH - 16, 0) : undefined;
  const y = parentBounds ? Math.max(parentBounds.y, 0) : undefined;

  const win = new BrowserWindow({
    width: SETTINGS_WIDTH,
    height: SETTINGS_HEIGHT,
    x,
    y,
    frame: false,
    transparent: false,
    resizable: false,
    show: false,
    fullscreenable: false,
    backgroundColor: "#141722",
    webPreferences: {
      preload: path.resolve(__dirname, "../electron/preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    win.loadURL(`${devServerUrl}/settings.html`);
  } else {
    win.loadFile(path.resolve(__dirname, "../dist/settings.html"));
  }

  win.once("ready-to-show", () => {
    win.show();
    win.focus();
  });

  win.on("closed", () => {
    if (settingsWindow === win) {
      settingsWindow = null;
    }
  });

  settingsWindow = win;

  if (!chatSettingsCache) {
    void ensureChatSettingsLoaded().catch(() => {
      chatSettingsCache = null;
    });
  }
};

ipcMain.on("desktop-pet:set-mouse-passthrough", (event, enabled: boolean) => {
  const win = BrowserWindow.fromWebContents(event.sender) ?? mainWindow;
  if (!win) {
    return;
  }

  win.setIgnoreMouseEvents(Boolean(enabled), { forward: true });
});

ipcMain.on("desktop-pet:set-pointer-interactive", (event, enabled: boolean) => {
  const win = BrowserWindow.fromWebContents(event.sender) ?? mainWindow;
  if (!win) {
    return;
  }

  win.setIgnoreMouseEvents(!Boolean(enabled), { forward: true });
});

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
    followCursor: active.followCursor ?? true
  };
});

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
      followCursor: item.followCursor ?? true
    }))
  };
});

ipcMain.handle("desktop-pet:get-chat-settings", async () => {
  const settings = await ensureChatSettingsLoaded();
  return settings;
});

ipcMain.handle("desktop-pet:get-latest-ai-message", async (_event, sessionId?: string) => {
  const resolvedSessionId = sessionId || getActiveModelRecord().sessionId;
  return {
    sessionId: resolvedSessionId,
    latestAiMessage: await fetchLatestAiMessageBySessionId(resolvedSessionId)
  };
});

ipcMain.handle("desktop-pet:update-chat-settings", async (_event, payload: ChatSettingsData) => {
  chatSettingsCache = {
    session_id: payload.session_id,
    model_name: payload.model_name,
    openai_api_key: payload.openai_api_key,
    openai_base_url: payload.openai_base_url,
    temperature: payload.temperature,
    system_prompt: payload.system_prompt,
    tools_list: [...payload.tools_list]
  };

  const res = await fetch(`${backendBaseUrl}/chat_settings`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(chatSettingsCache)
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `更新 chat_settings 失败: ${res.status}`);
  }

  const result = await parseJsonSafe<{ msg?: string; code?: number }>(res);
  if (!result || result.code !== 200) {
    throw new Error(result?.msg || "更新 chat_settings 失败：返回格式错误");
  }

  return {
    data: null,
    msg: result.msg ?? "success",
    code: 200
  };
});

ipcMain.handle("desktop-pet:get-available-tools", () => {
  return {
    tools: loadAvailableTools()
  };
});

ipcMain.handle(
  "desktop-pet:update-model-transform",
  (_event, payload: { modelId: string; offsetX?: number; offsetY?: number; userScale?: number; followCursor?: boolean }) => {
    const config = loadModelConfig();
    const target = config.models.find((item) => item.id === payload.modelId);
    if (!target) {
      throw new Error("模型不存在");
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
      followCursor: target.followCursor ?? true
    };
  }
);

ipcMain.handle("desktop-pet:preview-live2d-import", async () => {
  const chooser = settingsWindow && !settingsWindow.isDestroyed() ? settingsWindow : mainWindow;
  if (!chooser) {
    return null;
  }

  const result = await dialog.showOpenDialog(chooser, {
    title: "选择 Live2D 模型文件夹",
    properties: ["openDirectory"]
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return inspectImportSource(result.filePaths[0]);
});

ipcMain.handle("desktop-pet:import-live2d-model", async (_event, payload?: { selectedPath: string; suggestedName?: string }) => {
  if (!payload?.selectedPath) {
    throw new Error("缺少导入路径");
  }

  const preview = inspectImportSource(payload.selectedPath);
  const modelName = sanitizeModelName(payload.suggestedName || preview.suggestedName);
  const destDir = resolveUniqueModelDir(modelName);

  copyDirectory(preview.selectedPath, destDir);

  const entryName = findModel3JsonRelativePath(destDir);
  if (!entryName) {
    fs.rmSync(destDir, { recursive: true, force: true });
    throw new Error("未找到 .model3.json，请确认导入的是完整 Live2D 模型");
  }

  const modelId = `model-${randomUUID()}`;
  const record: ModelRecord = {
    id: modelId,
    name: path.basename(destDir),
    sessionId: randomUUID(),
    source: "custom",
    entry: entryName,
    rootDir: toPosixRelativeFrom(USER_DATA_DIR, destDir),
    offsetX: 0,
    offsetY: 0,
    userScale: 1,
    followCursor: true
  };

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
  notifyModelChanged();

  return {
    id: record.id,
    name: record.name,
    sessionId: record.sessionId,
    source: record.source
  };
});

ipcMain.handle("desktop-pet:delete-model", async (_event, modelId: string) => {
  const config = loadModelConfig();
  const target = config.models.find((item) => item.id === modelId);
  if (!target) {
    throw new Error("模型不存在");
  }

  if (target.source === "builtin") {
    throw new Error("默认模型不可删除");
  }

  await deleteChatSettingsBySessionId(target.sessionId);

  if (target.rootDir) {
    fs.rmSync(resolveRootDirAbsolute(target.rootDir), { recursive: true, force: true });
  }

  config.models = config.models.filter((item) => item.id !== modelId);
  if (config.models.length === 0) {
    const fallback = createDefaultModelConfig();
    saveModelConfig(fallback);
    notifyModelChanged();
    return {
      activeModelId: fallback.activeModelId
    };
  }

  if (config.activeModelId === modelId) {
    const builtin = config.models.find((item) => item.id === "builtin-hiyori")
      ?? config.models.find((item) => item.source === "builtin")
      ?? config.models[0];
    config.activeModelId = builtin.id;
  }

  saveModelConfig(config);
  notifyModelChanged();

  return {
    activeModelId: config.activeModelId
  };
});

ipcMain.handle("desktop-pet:set-active-model", (_event, modelId: string) => {
  const config = loadModelConfig();
  if (!config.models.some((item) => item.id === modelId)) {
    throw new Error("模型不存在");
  }

  config.activeModelId = modelId;
  saveModelConfig(config);
  notifyModelChanged();

  return {
    activeModelId: config.activeModelId
  };
});

ipcMain.on("desktop-pet:open-settings-window", () => {
  openSettingsWindow();
});

ipcMain.on("desktop-pet:minimize-current-window", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  win?.minimize();
});

ipcMain.on("desktop-pet:close-current-window", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  win?.close();
});

ipcMain.handle("desktop-pet:chat", async (event, payload: string | { message: string; sessionId?: string; requestId?: string }) => {
  const message = typeof payload === "string" ? payload : payload.message;
  const sessionId = typeof payload === "string" ? undefined : payload.sessionId;
  const requestId = typeof payload === "string" ? undefined : payload.requestId;
  const body: { message: string; session_id?: string } = { message };
  if (sessionId) {
    body.session_id = sessionId;
  }
  const abortController = new AbortController();
  const timeoutTimer = setTimeout(() => {
    abortController.abort();
  }, CHAT_REQUEST_TIMEOUT_MS);

  try {
    const res = await net.fetch(`${backendBaseUrl}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body),
      signal: abortController.signal
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `请求失败: ${res.status}`);
    }

    if (!res.body) {
      throw new Error("聊天接口返回格式错误：缺少响应流");
    }

    const decoder = new TextDecoder("utf-8");
    const reader = res.body.getReader();
    let streamBuffer = "";
    let aggregatedResponse = "";

    const processEventBlock = (block: string) => {
      const lines = block
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

      let eventName = "message";
      const dataLines: string[] = [];

      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }

      if (dataLines.length === 0) {
        return { done: false };
      }

      const dataText = dataLines.join("\n");
      if (dataText === "[DONE]") {
        return { done: true };
      }

      const parsed = JSON.parse(dataText) as { response?: string; detail?: string };
      if (eventName === "error") {
        throw new Error(parsed.detail || "聊天流返回错误事件");
      }

      if (typeof parsed.response === "string" && parsed.response.length > 0) {
        aggregatedResponse += parsed.response;
        if (requestId) {
          event.sender.send("desktop-pet:chat-chunk", {
            requestId,
            chunk: parsed.response,
            aggregated: aggregatedResponse
          });
        }
      }

      return { done: false };
    };

    let streamEnded = false;
    while (!streamEnded) {
      const readResult = await reader.read();
      if (readResult.done) {
        streamEnded = true;
        break;
      }

      streamBuffer += decoder.decode(readResult.value, { stream: true });
      const normalized = streamBuffer.replaceAll("\r\n", "\n");
      const eventBlocks = normalized.split("\n\n");
      streamBuffer = eventBlocks.pop() ?? "";

      for (const block of eventBlocks) {
        const state = processEventBlock(block);
        if (state.done) {
          streamEnded = true;
          break;
        }
      }
    }

    const remaining = streamBuffer.trim();
    if (remaining.length > 0) {
      processEventBlock(remaining);
    }

    return {
      response: aggregatedResponse,
      model: ""
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("聊天请求超时（900秒），请稍后重试");
    }
    if (message.includes("UND_ERR_BODY_TIMEOUT") || message.toLowerCase().includes("body timeout") || message.toLowerCase().includes("terminated")) {
      throw new Error("聊天请求超时（900秒），请稍后重试");
    }
    throw error;
  } finally {
    clearTimeout(timeoutTimer);
  }
});

app.whenReady().then(createWindow);

app.whenReady().then(() => {
  protocol.handle("live2d", (request) => {
    try {
      const requestUrl = new URL(request.url);
      const modelId = requestUrl.hostname;
      const relPath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, "");
      const config = loadModelConfig();
      const model = config.models.find((item) => item.id === modelId && item.source === "custom");
      if (!model?.rootDir) {
        return new Response("Model not found", { status: 404 });
      }

      const rootDir = resolveRootDirAbsolute(model.rootDir);
      const absoluteFilePath = path.normalize(path.join(rootDir, relPath));
      const normalizedRoot = path.normalize(`${rootDir}${path.sep}`);
      if (!absoluteFilePath.startsWith(normalizedRoot)) {
        return new Response("Forbidden", { status: 403 });
      }

      return net.fetch(pathToFileURL(absoluteFilePath).toString());
    } catch {
      return new Response("Bad request", { status: 400 });
    }
  });
});

app.whenReady().then(() => {
  cursorSyncTimer = setInterval(() => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }

    const cursor = screen.getCursorScreenPoint();
    const bounds = mainWindow.getBounds();
    const display = screen.getDisplayNearestPoint(cursor);
    const workArea = display.workArea;
    const localX = cursor.x - bounds.x;
    const localY = cursor.y - bounds.y;
    const insideWindow = localX >= 0 && localX <= bounds.width && localY >= 0 && localY <= bounds.height;

    mainWindow.webContents.send("desktop-pet:cursor", {
      localX,
      localY,
      screenX: cursor.x,
      screenY: cursor.y,
      windowX: bounds.x,
      windowY: bounds.y,
      windowWidth: bounds.width,
      windowHeight: bounds.height,
      displayX: workArea.x,
      displayY: workArea.y,
      displayWidth: workArea.width,
      displayHeight: workArea.height,
      insideWindow
    });
  }, 16);
});

app.on("window-all-closed", () => {
  if (cursorSyncTimer) {
    clearInterval(cursorSyncTimer);
    cursorSyncTimer = null;
  }

  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("browser-window-created", (_event, win) => {
  win.on("closed", () => {
    if (mainWindow === win) {
      mainWindow = null;
    }
    if (settingsWindow === win) {
      settingsWindow = null;
    }
  });
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
