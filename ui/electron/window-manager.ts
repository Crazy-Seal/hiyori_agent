/**
 * Electron 窗口管理
 */

import { app, BrowserWindow, screen } from "electron";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  WINDOW_WIDTH,
  WINDOW_HEIGHT,
  SETTINGS_WIDTH,
  SETTINGS_HEIGHT,
  LOG_WINDOW_WIDTH,
  LOG_WINDOW_HEIGHT,
  LOG_WINDOW_MIN_WIDTH,
  LOG_WINDOW_MIN_HEIGHT,
} from "./config.js";
import type { LogBatch } from "../shared-types.js";
import { appendFrontendLog, captureRendererLogs } from "./logging/app-logger.js";
import {
  createTrustedRendererPolicy,
  describeRendererUrl,
  isTrustedRendererUrl,
} from "./renderer-security.js";
import { installNavigationGuards } from "./navigation-guards.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const productionIndexPath = path.resolve(__dirname, "../../dist/index.html");
const productionSettingsPath = path.resolve(__dirname, "../../dist/settings.html");
const productionLogsPath = path.resolve(__dirname, "../../dist/logs.html");
const rendererPolicy = createTrustedRendererPolicy({
  devServerUrl: process.env.VITE_DEV_SERVER_URL,
  productionEntryUrls: [
    pathToFileURL(productionIndexPath).href,
    pathToFileURL(productionSettingsPath).href,
    pathToFileURL(productionLogsPath).href,
  ],
});

export const getTrustedRendererPolicy = () => rendererPolicy;

const logBlockedNavigation = (kind: string, targetUrl: string): void => {
  appendFrontendLog(
    "warn",
    "renderer-security",
    `拒绝窗口${kind}: target=${describeRendererUrl(targetUrl)}`,
  );
};

const protectApplicationWindow = (win: BrowserWindow, scope: string): void => {
  installNavigationGuards(
    win.webContents,
    (targetUrl) => isTrustedRendererUrl(targetUrl, rendererPolicy),
    logBlockedNavigation
  );
  captureRendererLogs(win, scope);
};

/**
 * 主窗口引用
 */
let mainWindow: BrowserWindow | null = null;

/**
 * 设置窗口引用
 */
let settingsWindow: BrowserWindow | null = null;

/** 日志控制台窗口引用。 */
let logWindow: BrowserWindow | null = null;

/**
 * 图片预览窗口引用
 */
let imagePreviewWindow: BrowserWindow | null = null;

/**
 * 获取主窗口
 */
export const getMainWindow = (): BrowserWindow | null => {
  return mainWindow;
};

/**
 * 获取设置窗口
 */
export const getSettingsWindow = (): BrowserWindow | null => {
  return settingsWindow;
};

export const getLogWindow = (): BrowserWindow | null => logWindow;

/**
 * 设置主窗口引用
 */
export const setMainWindow = (win: BrowserWindow | null): void => {
  mainWindow = win;
};

/**
 * 设置设置窗口引用
 */
export const setSettingsWindow = (win: BrowserWindow | null): void => {
  settingsWindow = win;
};

/**
 * 创建主窗口
 */
export const createMainWindow = (): BrowserWindow => {
  const display = screen.getPrimaryDisplay();
  const { x, y, width, height } = display.workArea;
  const windowX = x + width - WINDOW_WIDTH;
  const windowY = y + height - WINDOW_HEIGHT;

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
      preload: path.resolve(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  protectApplicationWindow(win, "main-window");

  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true });
  mainWindow = win;

  if (rendererPolicy.mode === "development") {
    win.loadURL(rendererPolicy.origin);
    // 开发模式下打开开发者工具
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(productionIndexPath);
  }

  return win;
};

/**
 * 打开设置窗口
 */
export const openSettingsWindow = (): void => {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.focus();
    return;
  }

  // 居中显示
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workArea;
  const x = Math.floor((width - SETTINGS_WIDTH) / 2);
  const y = Math.floor((height - SETTINGS_HEIGHT) / 2);

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
      preload: path.resolve(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  protectApplicationWindow(win, "settings-window");

  if (rendererPolicy.mode === "development") {
    win.loadURL(`${rendererPolicy.origin}/settings.html`);
  } else {
    win.loadFile(productionSettingsPath);
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
};

/** 创建或聚焦前后端实时日志控制台。 */
export const openLogWindow = (): BrowserWindow => {
  if (logWindow && !logWindow.isDestroyed()) {
    if (logWindow.isMinimized()) logWindow.restore();
    logWindow.show();
    logWindow.focus();
    return logWindow;
  }

  const win = new BrowserWindow({
    width: LOG_WINDOW_WIDTH,
    height: LOG_WINDOW_HEIGHT,
    minWidth: LOG_WINDOW_MIN_WIDTH,
    minHeight: LOG_WINDOW_MIN_HEIGHT,
    center: true,
    frame: false,
    transparent: false,
    resizable: true,
    show: false,
    fullscreenable: false,
    backgroundColor: "#141722",
    webPreferences: {
      preload: path.resolve(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  protectApplicationWindow(win, "log-window");
  if (rendererPolicy.mode === "development") {
    void win.loadURL(`${rendererPolicy.origin}/logs.html`);
  } else {
    void win.loadFile(productionLogsPath);
  }
  win.once("ready-to-show", () => {
    win.show();
    win.focus();
  });
  win.on("closed", () => {
    if (logWindow === win) logWindow = null;
  });
  logWindow = win;
  return win;
};

export const sendLogBatch = (batch: LogBatch): void => {
  if (!logWindow || logWindow.isDestroyed()) return;
  logWindow.webContents.send("desktop-pet:log-batch", batch);
};

/**
 * 打开图片预览窗口
 */
export const openImagePreviewWindow = (imageSrc: string): void => {
  // 如果已有预览窗口，先关闭
  if (imagePreviewWindow && !imagePreviewWindow.isDestroyed()) {
    imagePreviewWindow.close();
  }

  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workArea;

  // 窗口尺寸：最大 800x600，但不超过屏幕工作区域减去 100px 边距
  const winWidth = Math.min(800, width - 100);
  const winHeight = Math.min(600, height - 100);
  const x = Math.floor((width - winWidth) / 2);
  const y = Math.floor((height - winHeight) / 2);

  const win = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    x,
    y,
    frame: false,
    transparent: false,
    resizable: true,
    show: false,
    fullscreenable: false,
    backgroundColor: "#1a1a1a",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 创建简单的 HTML 内容显示图片
  const htmlContent = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          background: #1a1a1a;
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100vh;
          overflow: hidden;
          user-select: none;
        }
        /* 拖拽区域：整个窗口顶部 40px */
        .drag-region {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          height: 40px;
          -webkit-app-region: drag;
          z-index: 50;
        }
        .close-btn {
          position: fixed;
          top: 12px;
          right: 12px;
          width: 32px;
          height: 32px;
          border: none;
          border-radius: 8px;
          background: rgba(255, 82, 82, 0.9);
          color: #fff;
          font-size: 14px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
          box-shadow: 0 2px 8px rgba(0,0,0,0.3);
          transition: transform 0.15s, background 0.15s;
          -webkit-app-region: no-drag;
        }
        .close-btn:hover {
          transform: scale(1.1);
          background: rgba(255, 82, 82, 1);
        }
        img {
          max-width: 100%;
          max-height: 100vh;
          object-fit: contain;
          border-radius: 8px;
        }
      </style>
    </head>
    <body>
      <div class="drag-region"></div>
      <button class="close-btn" id="closeBtn">✕</button>
      <img src="${imageSrc}" alt="图片预览" />
      <script>
        document.getElementById('closeBtn').addEventListener('click', function() {
          window.close();
        });
        // ESC 键关闭
        document.addEventListener('keydown', function(e) {
          if (e.key === 'Escape') {
            window.close();
          }
        });
      </script>
    </body>
    </html>
  `;

  const previewUrl = `data:text/html;charset=utf-8,${encodeURIComponent(htmlContent)}`;
  installNavigationGuards(
    win.webContents,
    (targetUrl) => targetUrl === previewUrl,
    logBlockedNavigation
  );
  win.loadURL(previewUrl);

  win.once("ready-to-show", () => {
    win.show();
    win.focus();
  });

  win.on("closed", () => {
    imagePreviewWindow = null;
  });

  imagePreviewWindow = win;
};

/**
 * 初始化窗口事件监听
 */
export const initWindowEventListeners = (): void => {
  app.on("browser-window-created", (_event, win) => {
    win.on("closed", () => {
      if (mainWindow === win) {
        mainWindow = null;
      }
      if (settingsWindow === win) {
        settingsWindow = null;
      }
      if (logWindow === win) {
        logWindow = null;
      }
    });
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
};
