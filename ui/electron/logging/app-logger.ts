import type { BrowserWindow } from "electron";
import { mkdirSync } from "node:fs";

import type {
  LogBatch,
  LogLevel,
  LogSide,
  LogSnapshot,
  LogSource,
} from "../../shared-types.js";
import { LogHub } from "./log-core.js";
import { RollingLogWriter } from "./rolling-log-writer.js";

const MAX_LOG_BYTES = 10 * 1024 * 1024;
const MAX_LOG_FILES = 5;
const rawStderrWrite = process.stderr.write.bind(process.stderr);
const logHub = new LogHub();
let logDirectory = "";

const describeError = (error: unknown): string => {
  if (error instanceof Error) {
    return error.stack || `${error.name}: ${error.message}`;
  }
  return String(error);
};

const reportWriterError = (side: LogSide, error: unknown): void => {
  rawStderrWrite(`[Ayaya Log] ${side} 日志写入失败: ${describeError(error)}\n`);
};

export const initializeLogFiles = (directory: string): void => {
  mkdirSync(directory, { recursive: true });
  logDirectory = directory;
  logHub.setWriter("frontend", new RollingLogWriter({
    directory,
    fileName: "frontend.log",
    maxBytes: MAX_LOG_BYTES,
    maxFiles: MAX_LOG_FILES,
    onError: (error) => reportWriterError("frontend", error),
  }));
  logHub.setWriter("backend", new RollingLogWriter({
    directory,
    fileName: "backend.log",
    maxBytes: MAX_LOG_BYTES,
    maxFiles: MAX_LOG_FILES,
    onError: (error) => reportWriterError("backend", error),
  }));
};

export const getLogDirectory = (): string => logDirectory;

export const registerSensitiveLogValue = (value: string): void => {
  logHub.addSensitiveValue(value);
};

export const appendFrontendLog = (
  level: LogLevel,
  scope: string,
  message: string,
  error?: unknown,
): void => {
  logHub.append({
    side: "frontend",
    source: "electron-main",
    level,
    scope,
    message: error === undefined ? message : `${message}\n${describeError(error)}`,
  });
};

export const appendBackendLog = (
  source: Extract<LogSource, "stdout" | "stderr">,
  level: LogLevel,
  message: string,
): void => {
  logHub.append({
    side: "backend",
    source,
    level,
    scope: "python",
    message,
  });
};

export const getLogSnapshot = (): LogSnapshot => logHub.getSnapshot();

export const getRecentLogs = (side: LogSide, limit: number) =>
  logHub.getRecent(side, limit);

export const clearLogBuffer = (side: LogSide): void => logHub.clear(side);

export const subscribeLogBatches = (listener: (batch: LogBatch) => void): (() => void) =>
  logHub.subscribe(listener);

export const closeLogFiles = (): Promise<void> => logHub.close();

const rendererLevel = (level: "info" | "warning" | "error" | "debug"): LogLevel => {
  if (level === "warning") return "warn";
  return level;
};

/** 捕获应用 renderer 的控制台输出，并限制单窗口的瞬时日志速率。 */
export const captureRendererLogs = (win: BrowserWindow, scope: string): void => {
  let windowStartedAt = Date.now();
  let acceptedInWindow = 0;
  let rateWarningWritten = false;
  win.webContents.on("console-message", (details) => {
    const now = Date.now();
    if (now - windowStartedAt >= 1_000) {
      windowStartedAt = now;
      acceptedInWindow = 0;
      rateWarningWritten = false;
    }
    acceptedInWindow += 1;
    if (acceptedInWindow > 200) {
      if (!rateWarningWritten) {
        rateWarningWritten = true;
        logHub.append({
          side: "frontend",
          source: "renderer",
          level: "warn",
          scope,
          message: "renderer 日志速率超过每秒 200 条，当前时间窗口的后续日志已丢弃",
        });
      }
      return;
    }
    logHub.append({
      side: "frontend",
      source: "renderer",
      level: rendererLevel(details.level),
      scope,
      message: details.message,
    });
  });
};
