import type { BackendUnexpectedExit } from "./backend-process.js";

/** 后端恢复对话框允许的用户选择。 */
export type BackendRecoveryChoice = "reconnect" | "exit";

/** 与 Electron API 解耦的后端恢复对话框模型。 */
export interface BackendRecoveryDialogModel {
  title: string;
  message: string;
  detail: string;
  buttons: [string, string];
  defaultId: number;
  cancelId: number;
}

interface BackendRecoveryDependencies {
  startBackend: () => Promise<void>;
  showDialog: (model: BackendRecoveryDialogModel) => Promise<BackendRecoveryChoice>;
  clearSettingsCache: () => void;
  quit: () => void;
  logError: (message: string, error: unknown) => void;
}

/** 后端异常退出后的交互恢复协调器。 */
export interface BackendRecoveryCoordinator {
  /** 串行处理一个成功就绪后的非预期退出事件。 */
  handleUnexpectedExit(event: BackendUnexpectedExit): void;

  /** 标记应用已进入退出流程，忽略尚未完成的恢复操作。 */
  beginShutdown(): void;
}

type RecoveryPhase = "idle" | "recovering" | "quitting";

const commonDialogFields = {
  buttons: ["重连", "退出"] as [string, string],
  defaultId: 0,
  cancelId: 1,
};

const createUnexpectedExitDialog = (
  event: BackendUnexpectedExit,
): BackendRecoveryDialogModel => ({
  title: "Ayaya 后端意外退出",
  message: "后端进程已停止，聊天、设置和 MCP 功能暂时不可用。",
  detail: event.message,
  ...commonDialogFields,
});

const createReconnectFailureDialog = (error: unknown): BackendRecoveryDialogModel => ({
  title: "Ayaya 后端重连失败",
  message: "无法重新启动后端。",
  detail: error instanceof Error ? error.message : String(error),
  ...commonDialogFields,
});

/**
 * 创建后端异常退出恢复协调器。
 *
 * Args:
 *   dependencies: 后端启动、对话框、缓存和应用退出依赖。
 *
 * Returns:
 *   串行管理重连或退出选择的恢复协调器。
 */
export const createBackendRecoveryCoordinator = (
  dependencies: BackendRecoveryDependencies,
): BackendRecoveryCoordinator => {
  let phase: RecoveryPhase = "idle";
  let pendingExit: BackendUnexpectedExit | null = null;
  const isQuitting = (): boolean => phase === "quitting";

  const runRecovery = async (initialEvent: BackendUnexpectedExit): Promise<void> => {
    let dialogModel = createUnexpectedExitDialog(initialEvent);
    while (phase === "recovering") {
      const choice = await dependencies.showDialog(dialogModel);
      if (isQuitting()) return;
      if (choice === "exit") {
        phase = "quitting";
        dependencies.quit();
        return;
      }

      try {
        await dependencies.startBackend();
        if (isQuitting()) return;
        dependencies.clearSettingsCache();
      } catch (error) {
        if (isQuitting()) return;
        dependencies.logError("后端重连失败", error);
        dialogModel = createReconnectFailureDialog(error);
        continue;
      }

      if (pendingExit) {
        const nextExit = pendingExit;
        pendingExit = null;
        dialogModel = createUnexpectedExitDialog(nextExit);
        continue;
      }
      phase = "idle";
    }
  };

  const handleUnexpectedExit = (event: BackendUnexpectedExit): void => {
    if (phase === "quitting") return;
    if (phase === "recovering") {
      pendingExit = event;
      return;
    }
    phase = "recovering";
    void runRecovery(event).catch((error) => {
      dependencies.logError("处理后端异常退出失败", error);
      if (phase !== "quitting") {
        phase = "quitting";
        dependencies.quit();
      }
    });
  };

  const beginShutdown = (): void => {
    phase = "quitting";
    pendingExit = null;
  };

  return { handleUnexpectedExit, beginShutdown };
};
