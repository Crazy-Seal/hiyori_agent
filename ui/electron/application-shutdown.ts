/** 应用关闭阶段。 */
type ShutdownPhase = "idle" | "stopping" | "complete";

interface ApplicationShutdownDependencies {
  beginBackendRecoveryShutdown: () => void;
  stopCursorTracking: () => void;
  stopBackend: () => Promise<void>;
  closeLogs: () => Promise<void>;
  quit: () => void;
  logError: (message: string, error: unknown) => void;
}

/** Electron 应用关闭协调器。 */
export interface ApplicationShutdownCoordinator {
  /** 幂等地停止受管资源并退出应用。 */
  requestShutdown(): Promise<void>;

  /** 返回应用是否已经进入关闭流程。 */
  isShuttingDown(): boolean;

  /** 返回受管资源清理是否已经完成。 */
  isComplete(): boolean;
}

/**
 * 创建应用关闭协调器。
 *
 * Args:
 *   dependencies: 恢复状态、光标、后端进程和 Electron 退出依赖。
 *
 * Returns:
 *   将所有关闭入口合并到同一 Promise 的协调器。
 */
export const createApplicationShutdownCoordinator = (
  dependencies: ApplicationShutdownDependencies,
): ApplicationShutdownCoordinator => {
  let phase: ShutdownPhase = "idle";
  let shutdownPromise: Promise<void> | null = null;

  const requestShutdown = (): Promise<void> => {
    if (shutdownPromise) return shutdownPromise;
    phase = "stopping";
    dependencies.beginBackendRecoveryShutdown();
    dependencies.stopCursorTracking();
    shutdownPromise = (async () => {
      try {
        await dependencies.stopBackend();
      } catch (error) {
        dependencies.logError("停止后端进程失败", error);
      }
      try {
        await dependencies.closeLogs();
      } catch (error) {
        dependencies.logError("刷新日志文件失败", error);
      }
      phase = "complete";
      dependencies.quit();
    })();
    return shutdownPromise;
  };

  return {
    requestShutdown,
    isShuttingDown: () => phase !== "idle",
    isComplete: () => phase === "complete",
  };
};
