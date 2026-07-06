export type SettingsToastVariant = "success" | "error";

export interface SettingsNotifier {
  success(message: string): void;
  error(message: string): void;
}

export interface SettingsToastTimer {
  setTimeout(callback: () => void, delayMs: number): unknown;
  clearTimeout(handle: unknown): void;
}

const TOAST_DURATION_MS = 3000;
const SUCCESS_ICON_PATH =
  "M12 2a10 10 0 1 0 10 10A10.01 10.01 0 0 0 12 2Zm-2 15-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8Z";
const ERROR_ICON_PATH =
  "M12 2a10 10 0 1 0 10 10A10.01 10.01 0 0 0 12 2Zm4.3 14.3-1.4 1.4-2.9-2.9-2.9 2.9-1.4-1.4 2.9-2.9-2.9-2.9 1.4-1.4 2.9 2.9 2.9-2.9 1.4 1.4-2.9 2.9Z";

const defaultTimer: SettingsToastTimer = {
  setTimeout: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export const getErrorMessage = (error: unknown): string => {
  if (error === null || error === undefined) {
    return "";
  }
  const message = (error instanceof Error ? error.message : String(error)).trim();
  if (/\bfetch failed\b/i.test(message) || /\bECONNREFUSED\b/i.test(message)) {
    return "未识别到后端";
  }
  return message;
};

export const appendErrorMessage = (prefix: string, error: unknown): string => {
  const detail = getErrorMessage(error);
  return detail ? `${prefix}：${detail}` : prefix;
};

export class SettingsToast implements SettingsNotifier {
  private timeoutHandle: unknown = null;
  private readonly messageElement: HTMLSpanElement;
  private readonly iconPath: SVGPathElement;

  constructor(
    private readonly element: HTMLDivElement,
    private readonly timer: SettingsToastTimer = defaultTimer
  ) {
    const messageElement = element.querySelector<HTMLSpanElement>(".settings-toast-message");
    const iconPath = element.querySelector<SVGPathElement>(".settings-toast-icon path");
    if (!messageElement || !iconPath) {
      throw new Error("设置提示框缺少消息或图标元素");
    }
    this.messageElement = messageElement;
    this.iconPath = iconPath;
  }

  success(message: string): void {
    this.show("success", message);
  }

  error(message: string): void {
    this.show("error", message);
  }

  hide(): void {
    this.clearTimer();
    this.element.hidden = true;
    this.messageElement.textContent = "";
    delete this.element.dataset.variant;
  }

  dispose(): void {
    this.hide();
  }

  private show(variant: SettingsToastVariant, message: string): void {
    this.clearTimer();
    this.element.dataset.variant = variant;
    this.iconPath.setAttribute("d", variant === "success" ? SUCCESS_ICON_PATH : ERROR_ICON_PATH);
    this.messageElement.textContent = message;
    this.element.hidden = false;
    this.timeoutHandle = this.timer.setTimeout(() => this.hide(), TOAST_DURATION_MS);
  }

  private clearTimer(): void {
    if (this.timeoutHandle === null) {
      return;
    }
    this.timer.clearTimeout(this.timeoutHandle);
    this.timeoutHandle = null;
  }
}
