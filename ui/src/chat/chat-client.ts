/**
 * 聊天客户端
 */

import { BubbleManager } from "./bubble.js";
import { ChatHistoryManager } from "./chat-history-manager.js";
import { ScreenshotConfirmDialog } from "./screenshot-confirm-dialog.js";
import { buildInterruptResponseMeta } from "./interrupt-response.js";
import { ToolCallToastManager } from "./tool-call-toast.js";
import type { ChatInterruptPayload, ChatResult, ControlScreenActionData } from "../types.js";

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

  private async captureScreenWithUserPreference(): Promise<{ dataUrl: string; width: number; height: number } | undefined> {
    const frontendSettings = await window.desktopPetApi.getFrontendSettings();
    const shouldHide = frontendSettings.hide_on_screenshot;
    try {
      if (shouldHide) {
        window.hideElementsForScreenshot?.();
        await this.delay(120);
      }
      return await window.desktopPetApi.captureScreen?.();
    } finally {
      if (shouldHide) {
        window.restoreElementsAfterScreenshot?.();
      }
    }
  }

  private async performControlScreenAction(action: ControlScreenActionData): Promise<{
    executed: boolean;
    error?: string;
    screenshot?: { dataUrl: string; width: number; height: number };
  }> {
    const frontendSettings = await window.desktopPetApi.getFrontendSettings();
    const shouldHide = frontendSettings.hide_on_screenshot;
    try {
      if (shouldHide) {
        window.hideElementsForScreenshot?.();
        await this.delay(120);
      }

      const actionResult = await window.desktopPetApi.performScreenAction?.(action);
      if (!actionResult?.executed) {
        return {
          executed: false,
          error: actionResult?.error || "屏幕操作未完成",
        };
      }

      await this.delay(Math.max(0, action.wait_seconds) * 1000);
      const screenshot = await window.desktopPetApi.captureScreen?.();
      return { executed: true, screenshot };
    } finally {
      if (shouldHide) {
        window.restoreElementsAfterScreenshot?.();
      }
    }
  }

  private formatControlScreenMessage(action: ControlScreenActionData): string {
    const operationText: Record<ControlScreenActionData["operation"], string> = {
      click: "单击",
      double: "双击",
      right: "右键单击",
      scroll: action.scroll_direction === "up" ? "向上滚动" : "向下滚动",
    };
    const inputText = action.text ? `，并输入“${action.text}”` : "";
    const enterText = action.text && action.press_enter ? "后按回车" : "";
    return `Agent 请求在屏幕坐标 (${action.coordinates.x}, ${action.coordinates.y}) 对“${action.target}”执行${operationText[action.operation]}${inputText}${enterText}。是否允许？`;
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async respondToInterrupt(
    interruptData: ChatInterruptPayload,
    streamRequestId: string
  ): Promise<ChatResult | undefined> {
    const interruptValue = interruptData.value;
    const responseMeta = buildInterruptResponseMeta(interruptValue, streamRequestId);
    if (interruptValue.type === "screenshot_request") {
      const approved = await this.screenshotConfirmDialog.open(
        interruptValue.message || "Agent 请求截取屏幕，是否允许？"
      );
      if (!approved) {
        return await window.desktopPetApi.screenshotRespond?.({
          sessionId: this.sessionId,
          ...responseMeta,
          approved: false,
        });
      }
      const screenshot = await this.captureScreenWithUserPreference();
      return await window.desktopPetApi.screenshotRespond?.({
        sessionId: this.sessionId,
        ...responseMeta,
        approved: true,
        screenshotData: screenshot?.dataUrl,
        width: screenshot?.width,
        height: screenshot?.height,
      });
    }

    if (interruptValue.type === "control_screen_capture_request") {
      const screenshot = await this.captureScreenWithUserPreference();
      return await window.desktopPetApi.controlScreenRespond?.({
        sessionId: this.sessionId,
        ...responseMeta,
        screenshotData: screenshot?.dataUrl,
        width: screenshot?.width,
        height: screenshot?.height,
      });
    }

    const action = interruptValue.data;
    const approved = await this.screenshotConfirmDialog.open(
      this.formatControlScreenMessage(action)
    );
    if (!approved) {
      return await window.desktopPetApi.controlScreenRespond?.({
        sessionId: this.sessionId,
        ...responseMeta,
        approved: false,
      });
    }
    const actionResult = await this.performControlScreenAction(action);
    return await window.desktopPetApi.controlScreenRespond?.({
      sessionId: this.sessionId,
      ...responseMeta,
      approved: true,
      executed: actionResult.executed,
      error: actionResult.error,
      screenshotData: actionResult.screenshot?.dataUrl,
      width: actionResult.screenshot?.width,
      height: actionResult.screenshot?.height,
    });
  }

  async restorePendingInterrupt(initialInterrupt: ChatInterruptPayload): Promise<void> {
    if (this.screenshotConfirmDialog.isOpen()) {
      return;
    }

    const requestId = `resume-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    let streamedText = "";
    this.sendBtn.disabled = true;
    this.chatHistory.showTypingIndicator();
    this.chatHistory.startStreaming();

    const unsubscribeChunk = window.desktopPetApi.onChatChunk(({ requestId: id, chunk }) => {
      if (id !== requestId) return;
      this.chatHistory.hideTypingIndicator();
      streamedText += chunk;
      const { text } = this.parseExpressionTags(streamedText);
      this.bubble.setText(text);
      this.chatHistory.updateLastAiMessage(text);
    });
    const unsubscribeTool = window.desktopPetApi.onToolCall?.((data) => {
      if (data.requestId !== requestId) return;
      this.chatHistory.showToolCallMessage(data.toolName);
      this.toolCallToast.show(data.toolName);
    });

    try {
      let interrupt: ChatInterruptPayload | undefined = initialInterrupt;
      let result: ChatResult | undefined;
      while (interrupt) {
        result = await this.respondToInterrupt(interrupt, requestId);
        interrupt = result?.interrupted ? result.interruptData : undefined;
      }
      const { text, tags } = this.parseExpressionTags(streamedText || result?.response || "");
      for (const tag of tags) this.playMotionForTag(tag);
      this.bubble.setText(text);
      this.chatHistory.updateLastAiMessage(text);
      this.chatHistory.finalizeStreamingMessage();
      await this.chatHistory.loadHistory(this.sessionId);
      this.onChatComplete?.();
    } catch (error) {
      const errorMessage = `恢复对话失败: ${String(error)}`;
      this.bubble.setText(errorMessage);
      this.chatHistory.abortStreaming();
      this.chatHistory.showErrorMessage(errorMessage);
      this.toolCallToast.showError(errorMessage);
    } finally {
      unsubscribeChunk();
      unsubscribeTool?.();
      this.chatHistory.hideTypingIndicator();
      this.sendBtn.disabled = false;
      this.input.focus();
    }
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
      if (cleanText) {
        this.chatHistory.updateLastAiMessage(cleanText);
      }
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

    // 监听需要前端介入的中断事件
    const unsubscribeChatInterrupt = window.desktopPetApi.onChatInterrupt?.(
      async (interruptData: ChatInterruptPayload) => {
        stopCursor();
        this.isWaitingForScreenshotApproval = true;
        this.chatHistory.hideTypingIndicator();
        this.chatHistory.finalizeStreamingMessage();
        streamedText = "";
        this.chatHistory.startStreaming();

        try {
          startCursor();

          const respondResult = await this.respondToInterrupt(interruptData, requestId);

          if (respondResult?.interrupted) {
            return;
          }

          stopCursor();
          const rawResponse = streamedText || respondResult?.response || "";
          const { text: cleanText, tags } = this.parseExpressionTags(rawResponse);
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
          window.restoreElementsAfterScreenshot?.();

          stopCursor();
          const errorMessage = `前端中断响应失败: ${String(error)}`;
          this.bubble.setText(errorMessage);
          this.chatHistory.abortStreaming();
          this.chatHistory.showErrorMessage(errorMessage);
          this.toolCallToast.showError(errorMessage);

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
      this.chatHistory.abortStreaming();
      this.chatHistory.showErrorMessage(errorMessage);
      this.toolCallToast.showError(errorMessage);

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
