/**
 * 截屏确认对话框组件
 */

/**
 * 截屏确认对话框管理器
 */
export class ScreenshotConfirmDialog {
  private dialog: HTMLDivElement;
  private messageEl: HTMLDivElement;
  private titleEl: HTMLDivElement;
  private denyBtn: HTMLButtonElement;
  private allowBtn: HTMLButtonElement;
  private pendingResolver: ((approved: boolean) => void) | null = null;

  constructor() {
    this.dialog = document.getElementById("screenshot-confirm-dialog") as HTMLDivElement;
    this.messageEl = document.getElementById("screenshot-confirm-message") as HTMLDivElement;
    this.titleEl = document.getElementById("screenshot-confirm-title") as HTMLDivElement;
    this.denyBtn = document.getElementById("screenshot-deny-btn") as HTMLButtonElement;
    this.allowBtn = document.getElementById("screenshot-allow-btn") as HTMLButtonElement;

    this.setupEventListeners();
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners(): void {
    this.denyBtn.addEventListener("click", () => {
      this.close(false);
    });

    this.allowBtn.addEventListener("click", () => {
      this.close(true);
    });

    // 点击遮罩层关闭（视为拒绝）
    this.dialog.addEventListener("click", (event) => {
      if (event.target === this.dialog) {
        this.close(false);
      }
    });

    // ESC 键关闭（视为拒绝）
    this.dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        this.close(false);
      }
    });
  }

  /**
   * 关闭对话框
   */
  private close(approved: boolean): void {
    this.dialog.hidden = true;
    this.dialog.setAttribute("aria-hidden", "true");

    const resolver = this.pendingResolver;
    this.pendingResolver = null;
    if (resolver) {
      resolver(approved);
    }
  }

  /**
   * 打开确认对话框
   * @param message 可选的自定义消息
   * @returns Promise<boolean> 用户是否允许截屏
   */
  open(
    message?: string,
    title = "截屏请求",
    allowText = "允许",
    denyText = "拒绝"
  ): Promise<boolean> {
    this.titleEl.textContent = title;
    this.allowBtn.textContent = allowText;
    this.denyBtn.textContent = denyText;
    if (message) {
      this.messageEl.textContent = message;
    } else {
      this.messageEl.textContent = "Agent 请求截取屏幕，是否允许？";
    }

    this.dialog.hidden = false;
    this.dialog.setAttribute("aria-hidden", "false");

    // 聚焦到允许按钮
    this.allowBtn.focus();

    return new Promise<boolean>((resolve) => {
      this.pendingResolver = resolve;
    });
  }

  /**
   * 检查对话框是否打开
   */
  isOpen(): boolean {
    return !this.dialog.hidden;
  }
}
