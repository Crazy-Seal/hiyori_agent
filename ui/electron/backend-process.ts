import {
  spawn,
  type ChildProcess,
  type SpawnOptions,
} from "node:child_process";
import { randomBytes } from "node:crypto";

import type { LogLevel } from "../shared-types.js";
import { AYAYA_BACKEND_BASE_URL, WORKSPACE_ROOT } from "./config.js";
import { backendFetch, configureBackendClient } from "./backend-client.js";
import {
  buildBackendPythonEnvironment,
  createBackendPythonResolver,
  type ResolvedBackendPython,
} from "./backend-python.js";
import {
  appendBackendLog,
  appendFrontendLog,
  registerSensitiveLogValue,
} from "./logging/app-logger.js";
import { BackendLineDecoder, inferBackendLevel } from "./logging/log-core.js";

const DEFAULT_STARTUP_TIMEOUT_MS = 30_000;
const DEFAULT_POLL_INTERVAL_MS = 200;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 5_000;

type SpawnProcess = (
  command: string,
  args: readonly string[],
  options: SpawnOptions,
) => ChildProcess;

interface BackendProcessDependencies {
  env: NodeJS.ProcessEnv;
  workspaceRoot: string;
  backendBaseUrl: string;
  spawnProcess: SpawnProcess;
  configureClient: (token: string) => void;
  createToken: () => string;
  resolvePythonExecutable: (signal?: AbortSignal) => Promise<ResolvedBackendPython>;
  fetchBackend: (path: string, init?: RequestInit) => Promise<Response>;
  terminateProcess: (child: ChildProcess) => Promise<void>;
  pollIntervalMs: number;
  startupTimeoutMs: number;
  shutdownTimeoutMs: number;
  platform: NodeJS.Platform;
  ownerPid: number;
  logError: (message: string, error: unknown) => void;
  appendBackendLog: (
    source: "stdout" | "stderr",
    level: LogLevel,
    message: string,
  ) => void;
  registerSensitiveValue: (value: string) => void;
}

/** 后端进程在成功就绪后的非预期退出信息。 */
export interface BackendUnexpectedExit {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  message: string;
}

type BackendUnexpectedExitListener = (event: BackendUnexpectedExit) => void;

/** Electron 后端进程控制器。 */
export interface BackendProcessController {
  /** 启动受管后端，或连接已由外部启动的后端。 */
  startBackend(): Promise<void>;

  /** 请求后端优雅退出，并在超时后终止受管子进程。 */
  stopBackend(): Promise<void>;

  /** 订阅成功就绪后的非预期退出事件。 */
  onUnexpectedExit(listener: BackendUnexpectedExitListener): () => void;
}

interface ManagedBackendGeneration {
  child: ChildProcess;
  startupComplete: boolean;
  expectedExit: boolean;
  unexpectedExitReported: boolean;
}

const isRunning = (child: ChildProcess): boolean =>
  child.exitCode === null && child.signalCode === null;

const createCancelledError = (): Error => new Error("后端启动已取消");

const delay = (milliseconds: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(createCancelledError());
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(createCancelledError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });

/** 终止后端进程树，并完整消费辅助进程的生命周期事件。 */
const terminateProcessTree = async (child: ChildProcess): Promise<void> => {
  if (!isRunning(child) || !child.pid) return;
  if (process.platform !== "win32") {
    try {
      child.kill("SIGKILL");
    } catch (error) {
      appendFrontendLog("error", "backend-process", "强制终止后端进程失败", error);
    }
    return;
  }

  await new Promise<void>((resolve) => {
    const taskkill = spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      windowsHide: true,
      stdio: "ignore",
    });
    let settled = false;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      resolve();
    };
    taskkill.once("error", finish);
    taskkill.once("exit", finish);
  });
};

const defaultDependencies: BackendProcessDependencies = {
  env: process.env,
  workspaceRoot: WORKSPACE_ROOT,
  backendBaseUrl: AYAYA_BACKEND_BASE_URL,
  spawnProcess: (command, args, options) => spawn(command, args, options),
  configureClient: configureBackendClient,
  createToken: () => randomBytes(32).toString("base64url"),
  resolvePythonExecutable: createBackendPythonResolver().resolve,
  fetchBackend: backendFetch,
  terminateProcess: terminateProcessTree,
  pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
  startupTimeoutMs: DEFAULT_STARTUP_TIMEOUT_MS,
  shutdownTimeoutMs: DEFAULT_SHUTDOWN_TIMEOUT_MS,
  platform: process.platform,
  ownerPid: process.pid,
  logError: (message, error) => appendFrontendLog("error", "backend-process", message, error),
  appendBackendLog,
  registerSensitiveValue: registerSensitiveLogValue,
};

const waitForExit = async (child: ChildProcess, timeoutMs: number): Promise<void> => {
  if (!isRunning(child)) return;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.removeListener("exit", finish);
      resolve();
    };
    const timer = setTimeout(finish, timeoutMs);
    child.once("exit", finish);
  });
};

/**
 * 创建隔离的后端进程控制器。
 *
 * Args:
 *   overrides: 仅供 Electron 组装和单元测试替换的进程、网络与时钟依赖。
 *
 * Returns:
 *   拥有独立子进程状态的后端进程控制器。
 */
export const createBackendProcessController = (
  overrides: Partial<BackendProcessDependencies> = {},
): BackendProcessController => {
  const dependencies = { ...defaultDependencies, ...overrides };
  if (!overrides.resolvePythonExecutable && overrides.env) {
    dependencies.resolvePythonExecutable = createBackendPythonResolver({
      env: dependencies.env,
      platform: dependencies.platform,
      spawnProcess: dependencies.spawnProcess,
    }).resolve;
  }
  const unexpectedExitListeners = new Set<BackendUnexpectedExitListener>();
  let activeGeneration: ManagedBackendGeneration | null = null;
  let activeStartup: {
    abortController: AbortController;
    completion: Promise<void>;
  } | null = null;
  let managed = false;

  const publishUnexpectedExit = (event: BackendUnexpectedExit): void => {
    dependencies.logError(event.message, event);
    for (const listener of unexpectedExitListeners) {
      try {
        listener(event);
      } catch (error) {
        dependencies.logError("处理后端异常退出事件失败", error);
      }
    }
  };

  const waitForReady = async (signal: AbortSignal): Promise<void> => {
    while (!signal.aborted) {
      try {
        const response = await dependencies.fetchBackend("/internal/ready");
        if (response.ok) return;
        if (response.status === 401) {
          throw new Error("端口上的服务不接受当前 API Token");
        }
      } catch (error) {
        if (error instanceof Error && error.message.includes("API Token")) {
          throw error;
        }
      }
      await delay(dependencies.pollIntervalMs, signal);
    }
    throw createCancelledError();
  };

  const performStart = async (abortController: AbortController): Promise<void> => {
    if (activeGeneration && isRunning(activeGeneration.child)) {
      throw new Error("后端进程已经启动");
    }
    activeGeneration = null;

    managed = dependencies.env.AYAYA_MANAGE_BACKEND !== "false";
    const token = managed
      ? dependencies.createToken()
      : (dependencies.env.AYAYA_API_TOKEN ?? "");
    if (!managed && token.length < 43) {
      throw new Error("外部后端模式必须显式提供至少 256 bit 的 AYAYA_API_TOKEN");
    }
    dependencies.configureClient(token);
    dependencies.registerSensitiveValue(token);

    let generation: ManagedBackendGeneration | null = null;
    let timeout: NodeJS.Timeout | undefined;
    try {
      const contenders: Array<Promise<void>> = [];
      if (managed) {
        const resolvedPython = await dependencies.resolvePythonExecutable(
          abortController.signal,
        );
        if (abortController.signal.aborted) throw createCancelledError();
        const childEnvironment = buildBackendPythonEnvironment(
          dependencies.env,
          resolvedPython,
          dependencies.platform,
        );
        childEnvironment.AYAYA_API_TOKEN = token;
        if (dependencies.platform === "win32") {
          childEnvironment.AYAYA_PARENT_PID = String(dependencies.ownerPid);
        }
        const current = dependencies.spawnProcess(
          resolvedPython.executable,
          ["-B", "-m", "app.server"],
          {
            cwd: dependencies.env.AYAYA_BACKEND_CWD || dependencies.workspaceRoot,
            env: childEnvironment,
            windowsHide: true,
            stdio: ["ignore", "pipe", "pipe"],
          },
        );
        const stdoutDecoder = new BackendLineDecoder((line) => {
          dependencies.appendBackendLog("stdout", inferBackendLevel(line), line);
        });
        const stderrDecoder = new BackendLineDecoder((line) => {
          dependencies.appendBackendLog("stderr", inferBackendLevel(line), line);
        });
        current.stdout?.on("data", (chunk: Buffer | string) => stdoutDecoder.write(chunk));
        current.stderr?.on("data", (chunk: Buffer | string) => stderrDecoder.write(chunk));
        current.stdout?.once("end", () => stdoutDecoder.end());
        current.stderr?.once("end", () => stderrDecoder.end());
        generation = {
          child: current,
          startupComplete: false,
          expectedExit: false,
          unexpectedExitReported: false,
        };
        activeGeneration = generation;
        const currentGeneration = generation;

        contenders.push(
          new Promise<void>((_resolve, reject) => {
            current.on("error", (error) => {
              if (!currentGeneration.startupComplete) {
                reject(error);
                return;
              }
              dependencies.logError("后端进程在就绪后报告错误", error);
            });
            current.once("exit", (code, signal) => {
              if (!currentGeneration.startupComplete) {
                const detail = signal ? `信号 ${signal}` : `退出码 ${String(code)}`;
                reject(new Error(`后端进程在就绪前退出（${detail}）`));
                return;
              }
              if (
                currentGeneration.expectedExit
                || currentGeneration.unexpectedExitReported
                || activeGeneration !== currentGeneration
              ) return;

              currentGeneration.unexpectedExitReported = true;
              activeGeneration = null;
              const detail = signal ? `信号 ${signal}` : `退出码 ${String(code)}`;
              publishUnexpectedExit({
                exitCode: code,
                signal,
                message: `后端进程意外退出（${detail}）`,
              });
            });
          }),
        );
      }
      if (!managed) {
        dependencies.appendBackendLog(
          "stderr",
          "info",
          "当前为外部后端模式，Electron 无法捕获外部 Python 进程的实时日志",
        );
      }

      contenders.unshift(waitForReady(abortController.signal));
      contenders.push(
        new Promise<void>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error(`等待后端就绪超时: ${dependencies.backendBaseUrl}`)),
            dependencies.startupTimeoutMs,
          );
        }),
      );

      await Promise.race(contenders);
      if (generation) generation.startupComplete = true;
    } catch (error) {
      if (generation) {
        generation.expectedExit = true;
        if (activeGeneration === generation) activeGeneration = null;
        await dependencies.terminateProcess(generation.child);
      }
      throw error;
    } finally {
      abortController.abort();
      if (timeout) clearTimeout(timeout);
    }
  };

  const startBackend = (): Promise<void> => {
    if (activeStartup) {
      throw new Error("后端正在启动");
    }
    const abortController = new AbortController();
    const startup = {
      abortController,
      completion: Promise.resolve(),
    };
    const completion = performStart(abortController).finally(() => {
      if (activeStartup === startup) activeStartup = null;
    });
    startup.completion = completion;
    activeStartup = startup;
    return completion;
  };

  const stopBackend = async (): Promise<void> => {
    const startup = activeStartup;
    if (startup) {
      startup.abortController.abort();
      try {
        await startup.completion;
      } catch {
        // 启动取消或失败已由启动调用方处理，继续检查是否仍有受管进程。
      }
    }
    if (!managed || !activeGeneration) return;
    const generation = activeGeneration;
    generation.expectedExit = true;
    activeGeneration = null;
    const current = generation.child;
    try {
      await dependencies.fetchBackend("/internal/shutdown", { method: "POST" });
    } catch {
      // 后端可能已经退出，继续等待进程状态即可。
    }
    await waitForExit(current, dependencies.shutdownTimeoutMs);
    if (isRunning(current)) {
      await dependencies.terminateProcess(current);
    }
  };

  const onUnexpectedExit = (listener: BackendUnexpectedExitListener): (() => void) => {
    unexpectedExitListeners.add(listener);
    return () => unexpectedExitListeners.delete(listener);
  };

  return { startBackend, stopBackend, onUnexpectedExit };
};

const defaultController = createBackendProcessController();

/** 启动或连接受认证保护的本地后端。 */
export const startBackend = (): Promise<void> => defaultController.startBackend();

/** 请求后端优雅退出，并在超时后终止受管子进程。 */
export const stopBackend = (): Promise<void> => defaultController.stopBackend();

/** 订阅默认受管后端成功就绪后的非预期退出事件。 */
export const onBackendUnexpectedExit = (
  listener: BackendUnexpectedExitListener,
): (() => void) => defaultController.onUnexpectedExit(listener);
