/**
 * Electron 主进程配置常量
 */

export const WINDOW_WIDTH = 460;
export const WINDOW_HEIGHT = 760;
export const SETTINGS_WIDTH = 820;
export const SETTINGS_HEIGHT = 520;
export const LOG_WINDOW_WIDTH = 1200;
export const LOG_WINDOW_HEIGHT = 720;
export const LOG_WINDOW_MIN_WIDTH = 900;
export const LOG_WINDOW_MIN_HEIGHT = 500;

export const CHAT_REQUEST_TIMEOUT_MS = 900_000;
export const CHAT_HISTORY_PAGE_SIZE = 200;
export const CHAT_HISTORY_MAX_PAGES = 500;

/** 根据 Electron 主进程环境解析后端基础地址。 */
export const resolveBackendBaseUrl = (env: NodeJS.ProcessEnv): string =>
  env.AYAYA_BACKEND_BASE_URL ?? "http://127.0.0.1:8000";

export const AYAYA_BACKEND_BASE_URL = resolveBackendBaseUrl(process.env);

import { fileURLToPath } from "node:url";
import path from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const UI_ROOT = path.resolve(__dirname, "..", "..");
export const WORKSPACE_ROOT = path.resolve(UI_ROOT, "..");
export const USER_DATA_DIR = path.join(UI_ROOT, "user_data");
export const IMPORTED_MODELS_DIR = path.join(USER_DATA_DIR, "live2d_models");
export const LEGACY_IMPORTED_MODELS_DIR = path.join(UI_ROOT, "dist", "live2d");
export const MODEL_CONFIG_PATH = path.join(USER_DATA_DIR, "models.json");
export const FRONTEND_SETTINGS_PATH = path.join(USER_DATA_DIR, "frontend_settings.json");
