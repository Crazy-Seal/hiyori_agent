import assert from "node:assert/strict";
import { spawn, type ChildProcess, type SpawnOptions } from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { test } from "node:test";

import type { LogLevel } from "../shared-types.js";
import {
  createBackendProcessController,
  startBackend,
  type BackendUnexpectedExit,
} from "../electron/backend-process.js";

void startBackend;

class FakeChildProcess extends EventEmitter {
  pid: number | undefined = 1234;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  stdout = new PassThrough();
  stderr = new PassThrough();
}

interface ControllerHarnessOptions {
  env?: NodeJS.ProcessEnv;
  ready?: () => Promise<Response>;
  resolvePythonExecutable?: (
    signal?: AbortSignal,
  ) => Promise<{ executable: string; environmentRoot: string }>;
  resolvedPython?: {
    executable: string;
    environmentRoot: string;
  };
  startupTimeoutMs?: number;
  shutdownTimeoutMs?: number;
}

const createHarness = (options: ControllerHarnessOptions = {}) => {
  const children: FakeChildProcess[] = [];
  const spawnCalls: Array<{ command: string; args: readonly string[]; options: SpawnOptions }> = [];
  const terminated: ChildProcess[] = [];
  const loggedErrors: unknown[] = [];
  const backendLogs: Array<{ source: "stdout" | "stderr"; level: LogLevel; message: string }> = [];
  let shutdownCalls = 0;
  const controller = createBackendProcessController({
    env: options.env ?? {},
    workspaceRoot: "E:\\code\\Ayaya",
    backendBaseUrl: "http://127.0.0.1:8000",
    spawnProcess: (command, args, spawnOptions) => {
      spawnCalls.push({ command, args, options: spawnOptions });
      const child = new FakeChildProcess();
      children.push(child);
      return child as unknown as ChildProcess;
    },
    configureClient: () => undefined,
    createToken: () => "t".repeat(43),
    resolvePythonExecutable: options.resolvePythonExecutable ?? (async () =>
      options.resolvedPython ?? ({
        executable: "D:\\Miniconda\\envs\\ayaya\\python.exe",
        environmentRoot: "D:\\Miniconda\\envs\\ayaya",
      })),
    fetchBackend: async (path) => {
      if (path === "/internal/shutdown") {
        shutdownCalls += 1;
        return new Response(null, { status: 200 });
      }
      return (options.ready ?? (async () => new Response(null, { status: 200 })))();
    },
    terminateProcess: async (process) => {
      terminated.push(process);
      (process as unknown as FakeChildProcess).exitCode = -1;
    },
    logError: (_message, error) => loggedErrors.push(error),
    appendBackendLog: (source, level, message) => {
      backendLogs.push({ source, level, message });
    },
    pollIntervalMs: 1,
    startupTimeoutMs: options.startupTimeoutMs ?? 100,
    shutdownTimeoutMs: options.shutdownTimeoutMs ?? 5,
  });
  return {
    get child() {
      const child = children.at(-1);
      assert.ok(child, "后端子进程尚未创建");
      return child;
    },
    children,
    controller,
    spawnCalls,
    terminated,
    loggedErrors,
    backendLogs,
    get shutdownCalls() {
      return shutdownCalls;
    },
  };
};

const waitForSpawn = async (): Promise<void> => {
  await new Promise<void>((resolve) => setImmediate(resolve));
};

test("Python 不存在时 startBackend 应拒绝而不是触发未处理 error", async () => {
  const moduleUrl = new URL("../electron/backend-process.js", import.meta.url).href;
  const script = `
    import { startBackend } from ${JSON.stringify(moduleUrl)};
    try {
      await startBackend();
      console.log("UNEXPECTED_SUCCESS");
      process.exitCode = 2;
    } catch (error) {
      console.log("REJECTED:" + (error instanceof Error ? error.message : String(error)));
    }
  `;
  const result = await new Promise<{ code: number | null; stdout: string; stderr: string }>(
    (resolve, reject) => {
      const child = spawn(process.execPath, ["--input-type=module", "--eval", script], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          AYAYA_MANAGE_BACKEND: "true",
          AYAYA_PYTHON_EXECUTABLE: "Z:\\definitely-missing\\python.exe",
          AYAYA_BACKEND_CWD: process.cwd(),
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let stdout = "";
      let stderr = "";
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (chunk: string) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk: string) => {
        stderr += chunk;
      });
      child.once("error", reject);
      child.once("close", (code) => resolve({ code, stdout, stderr }));
    },
  );

  assert.equal(result.code, 0, result.stderr);
  assert.match(result.stdout, /REJECTED:.*ENOENT/);
  assert.doesNotMatch(result.stderr, /Unhandled 'error' event/);
});

test("默认直接使用解析出的 ayaya Python 启动后端", async () => {
  const harness = createHarness();

  await harness.controller.startBackend();

  assert.equal(harness.spawnCalls[0]?.command, "D:\\Miniconda\\envs\\ayaya\\python.exe");
  assert.deepEqual(harness.spawnCalls[0]?.args, [
    "-B",
    "-m",
    "app.server",
  ]);
  assert.equal(
    (harness.spawnCalls[0]?.options.env as NodeJS.ProcessEnv).AYAYA_PARENT_PID,
    String(process.pid),
  );
  assert.deepEqual(harness.spawnCalls[0]?.options.stdio, ["ignore", "pipe", "pipe"]);
});

test("托管后端持续解析 stdout 和 stderr，退出时刷新残留行", async () => {
  const harness = createHarness();
  await harness.controller.startBackend();

  harness.child.stdout.write("application ");
  harness.child.stdout.write("ready\n");
  harness.child.stderr.write("INFO: Uvicorn running\r\nERROR: broken");
  harness.child.stdout.end();
  harness.child.stderr.end();
  await new Promise<void>((resolve) => setImmediate(resolve));

  assert.deepEqual(harness.backendLogs, [
    { source: "stdout", level: "info", message: "application ready" },
    { source: "stderr", level: "info", message: "INFO: Uvicorn running" },
    { source: "stderr", level: "error", message: "ERROR: broken" },
  ]);
});

test("外部后端模式不创建 Python，并写入无法捕获外部日志的提示", async () => {
  const harness = createHarness({
    env: {
      AYAYA_MANAGE_BACKEND: "false",
      AYAYA_API_TOKEN: "e".repeat(43),
    },
  });

  await harness.controller.startBackend();

  assert.equal(harness.children.length, 0);
  assert.match(harness.backendLogs[0]?.message ?? "", /无法捕获外部 Python/);
});

test("AYAYA_PYTHON_EXECUTABLE 覆盖默认 Conda 命令", async () => {
  const harness = createHarness({
    env: { AYAYA_PYTHON_EXECUTABLE: "D:\\Python\\python.exe" },
    resolvedPython: {
      executable: "D:\\Python\\python.exe",
      environmentRoot: "D:\\Python",
    },
  });

  await harness.controller.startBackend();

  assert.equal(harness.spawnCalls[0]?.command, "D:\\Python\\python.exe");
  assert.deepEqual(harness.spawnCalls[0]?.args, ["-B", "-m", "app.server"]);
});

test("子进程 error 会拒绝启动并清理进程引用", async () => {
  const harness = createHarness({ ready: () => new Promise(() => undefined) });
  const startup = harness.controller.startBackend();
  await waitForSpawn();

  harness.child.pid = undefined;
  harness.child.emit("error", Object.assign(new Error("spawn ENOENT"), { code: "ENOENT" }));

  await assert.rejects(startup, /ENOENT/);
  assert.equal(harness.terminated.length, 1);
  await harness.controller.stopBackend();
  assert.equal(harness.terminated.length, 1);
});

test("子进程在就绪前退出会立即拒绝启动", async () => {
  const harness = createHarness({ ready: () => new Promise(() => undefined) });
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  const startup = harness.controller.startBackend();
  await waitForSpawn();

  harness.child.exitCode = 1;
  harness.child.emit("exit", 1, null);

  await assert.rejects(startup, /就绪前退出/);
  assert.equal(harness.terminated.length, 1);
  assert.deepEqual(exits, []);
});

test("等待 ready 超时后会终止并清空受管进程", async () => {
  const harness = createHarness({
    ready: async () => {
      throw new Error("connection refused");
    },
    startupTimeoutMs: 10,
  });

  await assert.rejects(harness.controller.startBackend(), /等待后端就绪超时/);

  assert.equal(harness.terminated.length, 1);
  await harness.controller.stopBackend();
  assert.equal(harness.terminated.length, 1);
});

test("ready 成功后保留后端进程", async () => {
  const harness = createHarness();

  await harness.controller.startBackend();

  assert.equal(harness.terminated.length, 0);
});

test("ready 成功后的进程 error 会被安全记录", async () => {
  const harness = createHarness();
  await harness.controller.startBackend();
  const error = new Error("late process error");

  harness.child.emit("error", error);

  assert.deepEqual(harness.loggedErrors, [error]);
});

test("ready 后异常退出会清空当前进程并发布一次事件", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();

  harness.child.exitCode = 1;
  harness.child.emit("exit", 1, null);
  harness.child.emit("exit", 1, null);

  assert.deepEqual(exits, [{ exitCode: 1, signal: null, message: "后端进程意外退出（退出码 1）" }]);
  await harness.controller.startBackend();
  assert.equal(harness.spawnCalls.length, 2);
});

test("ready 后被信号终止会发布信号详情", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();

  harness.child.signalCode = "SIGTERM";
  harness.child.emit("exit", null, "SIGTERM");

  assert.deepEqual(exits, [{
    exitCode: null,
    signal: "SIGTERM",
    message: "后端进程意外退出（信号 SIGTERM）",
  }]);
});

test("ready 后未经 stop 的退出码 0 仍视为异常", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();

  harness.child.exitCode = 0;
  harness.child.emit("exit", 0, null);

  assert.equal(exits.length, 1);
  assert.equal(exits[0]?.exitCode, 0);
});

test("正常 stopBackend 导致的退出不会发布异常事件", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();

  const current = harness.child;
  const stopping = harness.controller.stopBackend();
  current.exitCode = 0;
  current.emit("exit", 0, null);
  await stopping;

  assert.deepEqual(exits, []);
});

test("取消异常退出订阅后不再接收事件", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  const unsubscribe = harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();
  unsubscribe();

  harness.child.exitCode = 1;
  harness.child.emit("exit", 1, null);

  assert.deepEqual(exits, []);
});

test("旧 generation 的延迟事件不会清空新进程", async () => {
  const harness = createHarness();
  const exits: BackendUnexpectedExit[] = [];
  harness.controller.onUnexpectedExit((event) => exits.push(event));
  await harness.controller.startBackend();
  const oldChild = harness.child;
  oldChild.exitCode = 1;
  oldChild.emit("exit", 1, null);

  await harness.controller.startBackend();
  const current = harness.child;
  oldChild.emit("exit", 2, null);
  const stopping = harness.controller.stopBackend();
  current.exitCode = 0;
  current.emit("exit", 0, null);
  await stopping;

  assert.equal(exits.length, 1);
  assert.equal(harness.shutdownCalls, 1);
});

test("优雅退出超时后只强制终止一次", async () => {
  const harness = createHarness({ shutdownTimeoutMs: 1 });
  await harness.controller.startBackend();

  await harness.controller.stopBackend();
  await harness.controller.stopBackend();

  assert.equal(harness.shutdownCalls, 1);
  assert.equal(harness.terminated.length, 1);
});

test("环境解析期间停止后端会取消启动且不创建 Python", async () => {
  let aborted = false;
  const harness = createHarness({
    resolvePythonExecutable: (signal) => new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => {
        aborted = true;
        reject(new Error("后端启动已取消"));
      }, { once: true });
    }),
  });
  const startup = harness.controller.startBackend();
  const rejected = assert.rejects(startup, /后端启动已取消/);

  await harness.controller.stopBackend();
  await rejected;

  assert.equal(aborted, true);
  assert.equal(harness.spawnCalls.length, 0);
});
