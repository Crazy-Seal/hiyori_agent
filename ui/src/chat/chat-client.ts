/**
 * 聊天客户端
 */

import { BubbleManager } from "./bubble.js";
import { ChatHistoryManager } from "./chat-history-manager.js";
import { ScreenshotConfirmDialog } from "./screenshot-confirm-dialog.js";
import { ToolCallToastManager } from "./tool-call-toast.js";

/**
 * 截屏中断数据（内层）
 */
type ScreenshotInterruptData = {
  type: "screenshot_request";
  request_id: string;
  message: string;
};

/**
 * 截屏中断载荷（外层 value 包装）
 */
type ScreenshotInterruptPayload = {
  value: ScreenshotInterruptData;
};

/**
 * 聊天客户端选项
 */
export interface ChatClientOptions {
  bubble: BubbleManager;
  chatHistory: ChatHistoryManager;
  sendBtn: HTMLButtonElement;
  input: HTMLTextAreaElement;
  sessionId: string;
  onChatComplete?: () => void;
}

/**
 * 聊天客户端
 */
export class ChatClient {
  private bubble: BubbleManager;
  private chatHistory: ChatHistoryManager;
  private sendBtn: HTMLButtonElement;
  private input: HTMLTextAreaElement;
  private sessionId: string;
  private onChatComplete?: () => void;
  private hasUserSubmittedMessage = false;
  private screenshotConfirmDialog: ScreenshotConfirmDialog;
  private toolCallToast: ToolCallToastManager;
  private isWaitingForScreenshotApproval = false;
  private playedLabels: Set<string> = new Set(); // 追踪已播放的标签

  /**
   * 解析消息中的表情标签
   * 返回 { text: 清理后的文本, tags: 标签数组（去重后） }
   */
  private parseExpressionTags(text: string): { text: string; tags: string[] } {
    const tagRegex = /<([^<>]+)>/g;
    const tags: string[] = [];
    const seen = new Set<string>(); // 本次解析已见过的标签
    let match: RegExpExecArray | null;

    while ((match = tagRegex.exec(text)) !== null) {
      const tag = match[1];
      if (!seen.has(tag)) {
        seen.add(tag);
        tags.push(tag);
      }
    }

    // 移除标签后的文本
    const cleanText = text.replace(tagRegex, "").trim();
    return { text: cleanText, tags };
  }

  /**
   * 播放标签对应的动作
   */
  private playMotionForTag(tag: string): void {
    // 避免同一个标签重复播放
    if (this.playedLabels.has(tag)) {
      return;
    }
    this.playedLabels.add(tag);
    window.playMotionByLabel?.(tag);
  }

  constructor(options: ChatClientOptions) {
    this.bubble = options.bubble;
    this.chatHistory = options.chatHistory;
    this.sendBtn = options.sendBtn;
    this.input = options.input;
    this.sessionId = options.sessionId;
    this.onChatComplete = options.onChatComplete;
    this.screenshotConfirmDialog = new ScreenshotConfirmDialog();
    this.toolCallToast = new ToolCallToastManager();
  }

  /**
   * 设置会话 ID
   */
  setSessionId(sessionId: string): void {
    this.sessionId = sessionId;
  }

  /**
   * 获取会话 ID
   */
  getSessionId(): string {
    return this.sessionId;
  }

  /**
   * 标记用户已提交消息
   */
  markUserSubmitted(): void {
    this.hasUserSubmittedMessage = true;
  }

  /**
   * 检查用户是否已提交消息
   */
  hasUserSubmitted(): boolean {
    return this.hasUserSubmittedMessage;
  }

  /**
   * 发送聊天消息
   */
  async sendMessage(images?: string[]): Promise<void> {
    this.markUserSubmitted();

    const message = this.input.value.trim();
    if (!message && (!images || images.length === 0)) {
      return;
    }

    // 添加用户消息到历史
    this.chatHistory.addMessage({
      role: "human",
      content: message,
      timestamp: new Date().toISOString(),
      images: images,  // 直接传递 data URL 数组，在气泡中显示图片
    });

    this.sendBtn.disabled = true;

    // 显示"正在输入"提示
    this.chatHistory.showTypingIndicator();

    const requestId = `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    let streamedText = "";
    let cursorVisible = true;
    let cursorTimer: ReturnType<typeof setInterval> | null = null;
    let firstChunkReceived = false;
    let hasPendingToolCallIndicator = false; // 追踪是否有待最终化的工具调用指示器
    this.playedLabels.clear(); // 清空已播放标签

    const renderStreamingBubble = () => {
      // 解析表情标签
      const { text: cleanText, tags } = this.parseExpressionTags(streamedText);

      // 播放标签对应的动作
      for (const tag of tags) {
        this.playMotionForTag(tag);
      }

      const baseText = cleanText || "思考中...";
      this.bubble.setText(`${baseText}${cursorVisible ? "▋" : ""}`);
      // 更新聊天历史中的 AI 消息（使用清理后的文本）
      this.chatHistory.updateLastAiMessage(baseText);
    };

    const stopCursor = () => {
      if (cursorTimer) {
        clearInterval(cursorTimer);
        cursorTimer = null;
      }
    };

    const startCursor = () => {
      if (cursorTimer) return;
      cursorTimer = setInterval(() => {
        cursorVisible = !cursorVisible;
        renderStreamingBubble();
      }, 380);
    };

    cursorTimer = setInterval(() => {
      cursorVisible = !cursorVisible;
      renderStreamingBubble();
    }, 380);

    // 启动流式响应状态
    this.chatHistory.startStreaming();

    renderStreamingBubble();

    const unsubscribeChatChunk = window.desktopPetApi.onChatChunk(({ requestId: chunkRequestId, chunk }) => {
      if (chunkRequestId !== requestId) {
        return;
      }

      // 收到第一个 chunk 时隐藏"正在输入"提示
      if (!firstChunkReceived) {
        firstChunkReceived = true;
        this.chatHistory.hideTypingIndicator();
      }

      // 如果有待最终化的工具调用指示器，将其改为完成状态
      if (hasPendingToolCallIndicator) {
        this.chatHistory.finalizeToolCallIndicator();
        hasPendingToolCallIndicator = false;
      }

      streamedText += chunk;
      renderStreamingBubble();
    });

    // 监听截屏中断事件
    const unsubscribeChatInterrupt = window.desktopPetApi.onChatInterrupt?.(
      async (interruptData: ScreenshotInterruptPayload) => {
        // 停止光标动画
        stopCursor();

        // 显示确认对话框
        const interruptMessage = interruptData.value?.message || "Agent 请求截取屏幕，是否允许？";
        const approved = await this.screenshotConfirmDialog.open(interruptMessage);

        // 用户确认后，调用 screenshot/respond 接口
        this.isWaitingForScreenshotApproval = true;
        this.chatHistory.hideTypingIndicator();

        try {
          // 重新开始光标动画
          startCursor();

          let respondResult;

          if (approved) {
            // 获取前端设置，判断是否需要隐藏界面
            const frontendSettings = await window.desktopPetApi.getFrontendSettings();
            const hideOnScreenshot = frontendSettings.hide_on_screenshot;

            // 用户允许，如果配置为隐藏则先隐藏界面
            if (hideOnScreenshot) {
              window.hideElementsForScreenshot?.();
            }

            // 截取屏幕
            const screenshot = await window.desktopPetApi.captureScreen?.();

            // 截屏完成后恢复界面
            if (hideOnScreenshot) {
              window.restoreElementsAfterScreenshot?.();
            }

            respondResult = await window.desktopPetApi.screenshotRespond?.(
              this.sessionId,
              true,
              requestId,
              screenshot?.dataUrl,
              screenshot?.width,
              screenshot?.height
            );
          } else {
            // 用户拒绝，直接响应
            respondResult = await window.desktopPetApi.screenshotRespond?.(
              this.sessionId,
              false,
              requestId
            );
          }

          // 检查是否又有中断（连续截屏）
          if (respondResult?.interrupted) {
            // 递归处理，由事件监听器处理下一个中断
            return;
          }

          // 流结束
          stopCursor();
          // 解析表情标签并清理文本
          const rawResponse = streamedText || respondResult?.response || "";
          const { text: cleanText, tags } = this.parseExpressionTags(rawResponse);
          // 播放标签对应的动作
          for (const tag of tags) {
            this.playMotionForTag(tag);
          }
          this.bubble.setText(cleanText);
          this.chatHistory.updateLastAiMessage(cleanText);
          this.chatHistory.finalizeStreamingMessage();
          this.input.value = "";
          // 重置输入框高度
          this.input.style.height = "auto";

          // 清理所有监听器
          unsubscribeChatChunk();
          unsubscribeChatInterrupt?.();
          unsubscribeToolCall?.();
          this.sendBtn.disabled = false;
          this.input.focus();
          this.onChatComplete?.();
        } catch (error) {
          // 出错时确保恢复界面
          window.restoreElementsAfterScreenshot?.();

          stopCursor();
          const errorMessage = `截屏响应失败: ${String(error)}`;
          this.bubble.setText(errorMessage);
          this.chatHistory.updateLastAiMessage(errorMessage);
          this.chatHistory.finalizeStreamingMessage();

          // 清理所有监听器
          unsubscribeChatChunk();
          unsubscribeChatInterrupt?.();
          unsubscribeToolCall?.();
          this.sendBtn.disabled = false;
          this.input.focus();
          this.onChatComplete?.();
        } finally {
          this.isWaitingForScreenshotApproval = false;
        }
      }
    );

    // 监听工具调用事件
    const unsubscribeToolCall = window.desktopPetApi.onToolCall?.((data) => {
      if (data.requestId !== requestId) {
        return;
      }
      // 在聊天历史中显示工具调用消息
      this.chatHistory.showToolCallMessage(data.toolName);
      // 在 Live2D 右侧显示提示框
      this.toolCallToast.show(data.toolName);
      // 标记有待最终化的工具调用指示器
      hasPendingToolCallIndicator = true;
    });

    // 监听 Agent 错误事件
    const unsubscribeAgentError = window.desktopPetApi.onChatAgentError?.((data) => {
      if (data.requestId !== requestId) {
        return;
      }
      // 停止光标动画
      stopCursor();
      // 隐藏正在输入提示
      this.chatHistory.hideTypingIndicator();
      // 停止流式状态
      this.chatHistory.stopStreaming();
      // 清空气泡
      this.bubble.setText("");
      // 在聊天历史中显示错误消息（灰色小框）
      const errorMsg = `出现错误: ${data.errorMessage}`;
      this.chatHistory.showErrorMessage(errorMsg);
      // 在 Live2D 右侧显示错误提示框
      this.toolCallToast.showError(errorMsg);

      // 清理监听器
      unsubscribeChatChunk();
      unsubscribeChatInterrupt?.();
      unsubscribeToolCall?.();
      unsubscribeAgentError?.();
      this.sendBtn.disabled = false;
      this.input.focus();
      this.onChatComplete?.();
    });

    // 标记是否被中断（用于 finally 块判断）
    let wasInterrupted = false;

    try {
      if (!window.desktopPetApi || typeof window.desktopPetApi.chat !== "function") {
        throw new Error("桌宠桥接未就绪，请重启桌宠程序");
      }

      const result = await window.desktopPetApi.chat(
        message,
        this.sessionId || undefined,
        requestId,
        images
      );

      // 检查是否被中断（截屏请求）
      if (result.interrupted) {
        wasInterrupted = true;
        // 中断事件会通过 onChatInterrupt 处理，这里不做任何事
        return;
      }

      stopCursor();
      // 解析表情标签并清理文本
      const { text: cleanText, tags } = this.parseExpressionTags(streamedText || result.response);
      // 播放标签对应的动作
      for (const tag of tags) {
        this.playMotionForTag(tag);
      }
      this.bubble.setText(cleanText);
      // 更新聊天历史中的最终 AI 消息
      this.chatHistory.updateLastAiMessage(cleanText);
      // 完成流式响应，分割句子渲染
      this.chatHistory.finalizeStreamingMessage();
      this.input.value = "";
      // 重置输入框高度
      this.input.style.height = "auto";

      // 清理监听器
      unsubscribeChatInterrupt?.();
      unsubscribeToolCall?.();
    } catch (error) {
      stopCursor();
      const errorMessage = `请求失败: ${String(error)}`;
      this.bubble.setText(errorMessage);
      this.chatHistory.updateLastAiMessage(errorMessage);
      this.chatHistory.finalizeStreamingMessage();

      unsubscribeChatInterrupt?.();
      unsubscribeToolCall?.();
    } finally {
      stopCursor();

      // 确保"正在输入"提示被隐藏
      this.chatHistory.hideTypingIndicator();

      // 只有非中断状态才清理监听器和释放发送按钮
      // 中断状态下，监听器在 onChatInterrupt 回调中清理
      if (!wasInterrupted) {
        unsubscribeChatChunk();
        this.sendBtn.disabled = false;
        this.input.focus();
        this.onChatComplete?.();
      }
    }
  }
}

/**
 * 启动最新 AI 消息加载
 */
export const startLatestAiMessageBootstrap = (
  sessionId: string,
  bubble: BubbleManager,
  hasUserSubmitted: () => boolean,
  onConnect?: () => void
): (() => void) => {
  let stopped = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const stop = () => {
    stopped = true;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  };

  const scheduleRetry = () => {
    if (stopped) {
      return;
    }

    retryTimer = setTimeout(() => {
      void run();
    }, 1000);
  };

  const run = async () => {
    if (stopped) {
      return;
    }

    try {
      const { latestAiMessage } = await window.desktopPetApi.getLatestAiMessage(sessionId);
      // 首次成功连接后端时触发回调（用于加载聊天历史）
      if (onConnect) {
        onConnect();
      }
      if (
        !hasUserSubmitted() &&
        typeof latestAiMessage === "string" &&
        latestAiMessage.trim().length > 0
      ) {
        bubble.setText(latestAiMessage.trim());
      }
      stop();
    } catch {
      scheduleRetry();
    }
  };

  void run();
  return stop;
};
