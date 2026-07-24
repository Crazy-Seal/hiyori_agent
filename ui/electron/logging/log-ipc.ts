import { shell } from "electron";

import type { LogBatch, LogSide } from "../../shared-types.js";
import { createTrustedIpcRegistrar } from "../ipc-security.js";
import type { TrustedRendererPolicy } from "../renderer-security.js";
import {
  clearLogBuffer,
  getLogDirectory,
  getLogSnapshot,
  subscribeLogBatches,
} from "./app-logger.js";

interface LogIpcOptions {
  policy: TrustedRendererPolicy;
  openLogWindow: () => void;
  sendBatch: (batch: LogBatch) => void;
}

const isLogSide = (value: unknown): value is LogSide =>
  value === "frontend" || value === "backend";

export const registerLogIpcHandlers = ({
  policy,
  openLogWindow,
  sendBatch,
}: LogIpcOptions): (() => void) => {
  const trustedIpc = createTrustedIpcRegistrar(policy);
  trustedIpc.on("desktop-pet:open-log-window", () => openLogWindow());
  trustedIpc.handle("desktop-pet:get-log-snapshot", () => getLogSnapshot());
  trustedIpc.handle("desktop-pet:clear-log-buffer", (_event, side: unknown) => {
    if (!isLogSide(side)) throw new Error("无效的日志分区");
    clearLogBuffer(side);
  });
  trustedIpc.handle("desktop-pet:open-log-directory", async () => {
    const directory = getLogDirectory();
    if (!directory) throw new Error("日志目录尚未初始化");
    const failure = await shell.openPath(directory);
    if (failure) throw new Error("无法打开日志目录");
  });
  return subscribeLogBatches(sendBatch);
};
