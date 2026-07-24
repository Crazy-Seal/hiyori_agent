import { spawn, type ChildProcess, type SpawnOptions } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";

const DEFAULT_DISCOVERY_TIMEOUT_MS = 10_000;
const MAX_STDOUT_BYTES = 1024 * 1024;
const MAX_STDERR_BYTES = 64 * 1024;

type SpawnProcess = (
  command: string,
  args: readonly string[],
  options: SpawnOptions,
) => ChildProcess;

interface BackendPythonResolverDependencies {
  env: NodeJS.ProcessEnv;
  platform: NodeJS.Platform;
  spawnProcess: SpawnProcess;
  fileExists: (filePath: string) => Promise<boolean>;
  timeoutMs: number;
}

/** 可直接启动后端的 Python 解释器信息。 */
export interface ResolvedBackendPython {
  executable: string;
  environmentRoot?: string;
}

/** 后端 Python 解释器解析器。 */
export interface BackendPythonResolver {
  /** 解析显式解释器或名为 ayaya 的 Conda 环境。 */
  resolve(signal?: AbortSignal): Promise<ResolvedBackendPython>;
}

const defaultFileExists = async (filePath: string): Promise<boolean> => {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
};

const defaultDependencies: BackendPythonResolverDependencies = {
  env: process.env,
  platform: process.platform,
  spawnProcess: (command, args, options) => spawn(command, args, options),
  fileExists: defaultFileExists,
  timeoutMs: DEFAULT_DISCOVERY_TIMEOUT_MS,
};

const createCancelledError = (): Error => new Error("后端启动已取消");

const terminateHelperProcess = (child: ChildProcess): void => {
  try {
    child.kill();
  } catch {
    // 进程可能尚未获得 PID 或已经退出，无需覆盖原始失败原因。
  }
};

/**
 * 创建后端 Python 解释器解析器。
 *
 * Args:
 *   overrides: 供 Electron 组装或测试替换的环境、进程和文件系统依赖。
 *
 * Returns:
 *   仅在内存中缓存本次解析结果的解释器解析器。
 */
export const createBackendPythonResolver = (
  overrides: Partial<BackendPythonResolverDependencies> = {},
): BackendPythonResolver => {
  const dependencies = { ...defaultDependencies, ...overrides };
  let cached: ResolvedBackendPython | undefined;

  const runCondaEnvironmentList = (signal?: AbortSignal): Promise<string> =>
    new Promise<string>((resolve, reject) => {
      if (signal?.aborted) {
        reject(createCancelledError());
        return;
      }

      let child: ChildProcess;
      try {
        child = dependencies.spawnProcess("conda", ["env", "list", "--json"], {
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });
      } catch (error) {
        reject(error);
        return;
      }

      let settled = false;
      let stdout = "";
      let stderr = "";
      const finish = (error?: unknown): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        if (error !== undefined) {
          reject(error);
        } else {
          resolve(stdout);
        }
      };
      const onAbort = (): void => {
        terminateHelperProcess(child);
        finish(createCancelledError());
      };
      const timer = setTimeout(() => {
        terminateHelperProcess(child);
        finish(new Error("查找 ayaya Conda 环境超时"));
      }, dependencies.timeoutMs);

      signal?.addEventListener("abort", onAbort, { once: true });
      child.stdout?.setEncoding("utf8");
      child.stderr?.setEncoding("utf8");
      child.stdout?.on("data", (chunk: string) => {
        if (settled) return;
        if (Buffer.byteLength(stdout) + Buffer.byteLength(chunk) > MAX_STDOUT_BYTES) {
          terminateHelperProcess(child);
          finish(new Error("Conda 环境列表输出超过大小限制"));
          return;
        }
        stdout += chunk;
      });
      child.stderr?.on("data", (chunk: string) => {
        if (settled || Buffer.byteLength(stderr) >= MAX_STDERR_BYTES) return;
        const remaining = MAX_STDERR_BYTES - Buffer.byteLength(stderr);
        stderr += Buffer.from(chunk).subarray(0, remaining).toString("utf8");
      });
      child.on("error", (error) => finish(error));
      child.once("close", (code, exitSignal) => {
        if (settled) return;
        if (code !== 0) {
          const detail = exitSignal
            ? `信号 ${exitSignal}`
            : `退出码 ${String(code)}`;
          const message = stderr.trim();
          finish(new Error(`无法查询 Conda 环境（${detail}）${message ? `：${message}` : ""}`));
          return;
        }
        finish();
      });
    });

  const resolve = async (signal?: AbortSignal): Promise<ResolvedBackendPython> => {
    if (signal?.aborted) throw createCancelledError();
    if (cached) return cached;

    const explicit = dependencies.env.AYAYA_PYTHON_EXECUTABLE?.trim();
    if (explicit) {
      cached = {
        executable: explicit,
      };
      return cached;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(await runCondaEnvironmentList(signal));
    } catch (error) {
      if (error instanceof Error && error.message === "后端启动已取消") throw error;
      if (error instanceof SyntaxError) {
        throw new Error("Conda 返回了无法解析的环境列表", { cause: error });
      }
      throw error;
    }
    if (
      typeof parsed !== "object"
      || parsed === null
      || !Array.isArray((parsed as { envs?: unknown }).envs)
    ) {
      throw new Error("Conda 返回的环境列表缺少 envs 字段");
    }

    const pathApi = dependencies.platform === "win32" ? path.win32 : path.posix;
    const candidates = (parsed as { envs: unknown[] }).envs.filter(
      (item): item is string =>
        typeof item === "string"
        && pathApi.basename(pathApi.normalize(item)).toLowerCase() === "ayaya",
    );
    if (candidates.length === 0) {
      throw new Error(
        "未找到名为 ayaya 的 Conda 环境，请创建该环境或设置 AYAYA_PYTHON_EXECUTABLE",
      );
    }
    if (candidates.length > 1) {
      throw new Error(
        "找到多个名为 ayaya 的 Conda 环境，请使用 AYAYA_PYTHON_EXECUTABLE 明确指定解释器",
      );
    }

    const environmentRoot = candidates[0];
    const executable = dependencies.platform === "win32"
      ? pathApi.join(environmentRoot, "python.exe")
      : pathApi.join(environmentRoot, "bin", "python");
    if (!await dependencies.fileExists(executable)) {
      throw new Error(
        "ayaya Conda 环境中不存在 Python 解释器，请修复环境或设置 AYAYA_PYTHON_EXECUTABLE",
      );
    }
    if (signal?.aborted) throw createCancelledError();

    cached = { executable, environmentRoot };
    return cached;
  };

  return { resolve };
};

/**
 * 为直接启动的环境 Python 补充必要的可执行文件搜索目录。
 *
 * Args:
 *   baseEnvironment: Electron 当前环境。
 *   resolvedPython: 已解析的解释器及环境根目录。
 *   platform: 当前 Node 平台。
 *
 * Returns:
 *   不修改输入对象的后端子进程环境。
 */
export const buildBackendPythonEnvironment = (
  baseEnvironment: NodeJS.ProcessEnv,
  resolvedPython: ResolvedBackendPython,
  platform: NodeJS.Platform,
): NodeJS.ProcessEnv => {
  const childEnvironment: NodeJS.ProcessEnv = {
    ...baseEnvironment,
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
  };
  if (!resolvedPython.environmentRoot) return childEnvironment;

  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const additions = platform === "win32"
    ? [
        resolvedPython.environmentRoot,
        pathApi.join(resolvedPython.environmentRoot, "Scripts"),
        pathApi.join(resolvedPython.environmentRoot, "Library", "bin"),
      ]
    : [pathApi.join(resolvedPython.environmentRoot, "bin")];
  const currentPathKey = Object.keys(childEnvironment).find(
    (key) => key.toLocaleLowerCase() === "path",
  ) ?? "PATH";
  const currentPath = childEnvironment[currentPathKey] ?? "";
  const delimiter = platform === "win32" ? ";" : ":";
  childEnvironment[currentPathKey] = [...additions, currentPath]
    .filter(Boolean)
    .join(delimiter);
  return childEnvironment;
};
