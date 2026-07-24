/**
 * 确认对话框组件
 */

/**
 * 确认对话框管理器
 */
export type ConfirmDialogVariant = "warning" | "danger";

export type ConfirmDialogOptions = {
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  variant: ConfirmDialogVariant;
};

const DELETE_MODEL_DEFAULTS: ConfirmDialogOptions = {
  title: "删除模型确认",
  message: "将删除该模型所有的配置文件和会话记忆，请谨慎操作",
  confirmText: "确认删除",
  cancelText: "取消",
  variant: "danger",
};

export class ConfirmDialog {
  private dialog: HTMLDivElement;
  private cancelBtn: HTMLButtonElement;
  private okBtn: HTMLButtonElement;
  private title: HTMLElement;
  private message: HTMLElement;
  private pendingResolver: ((confirmed: boolean) => void) | null = null;

  constructor(
    dialog: HTMLDivElement,
    cancelBtn: HTMLButtonElement,
    okBtn: HTMLButtonElement,
    title: HTMLElement,
    message: HTMLElement
  ) {
    this.dialog = dialog;
    this.cancelBtn = cancelBtn;
    this.okBtn = okBtn;
    this.title = title;
    this.message = message;

    this.setupEventListeners();
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners(): void {
    this.cancelBtn.addEventListener("click", () => {
      this.close(false);
    });

    this.okBtn.addEventListener("click", () => {
      this.close(true);
    });

    this.dialog.addEventListener("click", (event) => {
      if (event.target === this.dialog) {
        this.close(false);
      }
    });
  }

  /**
   * 关闭对话框
   */
  private close(confirmed: boolean): void {
    this.dialog.hidden = true;
    this.dialog.setAttribute("aria-hidden", "true");

    const resolver = this.pendingResolver;
    this.pendingResolver = null;
    if (resolver) {
      resolver(confirmed);
    }
  }

  /**
   * 打开确认对话框
   */
  open(options: ConfirmDialogOptions = DELETE_MODEL_DEFAULTS): Promise<boolean> {
    this.title.textContent = options.title;
    this.message.textContent = options.message;
    this.cancelBtn.textContent = options.cancelText;
    this.okBtn.textContent = options.confirmText;
    this.okBtn.classList.remove(
      "confirm-btn-danger",
      "confirm-btn-warning",
      "ui-button--danger",
      "ui-button--warning",
    );
    this.okBtn.classList.add(`confirm-btn-${options.variant}`);
    this.okBtn.classList.add(`ui-button--${options.variant}`);
    this.dialog.hidden = false;
    this.dialog.setAttribute("aria-hidden", "false");
    return new Promise<boolean>((resolve) => {
      this.pendingResolver = resolve;
    });
  }
}
