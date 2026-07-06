/**
 * 设置窗口入口
 */

import "../settings.css";

import { ConfirmDialog } from "./components/confirm-dialog.js";
import { SettingsToast, appendErrorMessage } from "./components/settings-toast.js";
import { ModelPage } from "./pages/model-page.js";
import { LlmPage } from "./pages/llm-page.js";
import { ToolsPage } from "./pages/tools-page.js";
import { MultimodalPage } from "./pages/multimodal-page.js";
import { MotionPage } from "./pages/motion-page.js";
import type {
  ChatSettingsState,
  ModelConfig,
  EditingState,
  ISettingsPage,
  PageRenderData,
  PageEventCallback,
  PageEvent,
  ToolItem,
} from "./types.js";

/**
 * 设置窗口应用（Controller）
 */
class SettingsApp {
  private sidebar: HTMLDivElement;
  private minBtn: HTMLButtonElement;
  private closeBtn: HTMLButtonElement;

  private modelPage: ModelPage;
  private llmPage: ISettingsPage;
  private toolsPage: ISettingsPage;
  private multimodalPage: MultimodalPage;
  private motionPage: ISettingsPage;
  private confirmDialog: ConfirmDialog;
  private toast: SettingsToast;

  private currentPage = "model";

  /** 已保存状态（来自后端，不可变） */
  private savedState: ChatSettingsState | null = null;
  /** 模型配置（已保存） */
  private modelConfig: ModelConfig | null = null;

  /** 页面映射 */
  private pages: Map<string, ISettingsPage | null> = new Map();

  constructor() {
    // 获取 DOM 元素
    this.sidebar = this.getElement("#settings-sidebar");
    this.minBtn = this.getElement("#settings-min-btn");
    this.closeBtn = this.getElement("#settings-close-btn");
    this.toast = new SettingsToast(this.getElement("#settings-toast"));

    // 初始化确认对话框
    this.confirmDialog = new ConfirmDialog(
      this.getElement("#delete-confirm-dialog"),
      this.getElement("#delete-confirm-cancel"),
      this.getElement("#delete-confirm-ok")
    );

    // 初始化模型管理页面
    this.modelPage = new ModelPage(
      this.getElement("#model-list"),
      this.getElement("#import-preview"),
      this.getElement("#preview-name"),
      this.getElement("#preview-type"),
      this.getElement("#preview-entry"),
      this.getElement("#confirm-import-btn"),
      this.getElement("#cancel-import-btn"),
      this.getElement("#import-model-btn"),
      this.getElement("#slider-offset-x"),
      this.getElement("#slider-offset-y"),
      this.getElement("#slider-offset-x-value"),
      this.getElement("#slider-offset-y-value"),
      this.getElement("#checkbox-follow-cursor"),
      this.confirmDialog,
      this.toast
    );

    // 初始化 LLM 配置页面
    this.llmPage = new LlmPage(
      this.getElement("#llm-base-url"),
      this.getElement("#llm-api-key"),
      this.getElement("#llm-model-name"),
      this.getElement("#llm-temperature"),
      this.getElement("#llm-system-prompt"),
      this.getElement("#llm-confirm-btn"),
      this.getElement("#llm-name"),
      this.getElement("#llm-feature"),
      this.getElement("#llm-character"),
      this.getElement("#llm-address"),
      this.getElement("#llm-characteristic"),
      this.getElement("#llm-constraint")
    );

    // 初始化工具配置页面
    this.toolsPage = new ToolsPage(
      this.getElement("#tools-table-body"),
      this.getElement("#tools-empty"),
      this.getElement("#tools-confirm-btn")
    );

    // 初始化多模态配置页面
    this.multimodalPage = new MultimodalPage(
      this.getElement("#checkbox-hide-on-screenshot")
    );

    // 初始化动作控制页面
    this.motionPage = new MotionPage(
      this.getElement("#motion-table-body"),
      this.getElement("#motion-empty"),
      this.getElement("#motion-confirm-btn"),
      this.getElement("#motion-system-prompt")
    );

    // 注册页面到映射
    this.pages.set("llm", this.llmPage);
    this.pages.set("tools", this.toolsPage);
    this.pages.set("motion", this.motionPage);

    // 设置事件回调
    const eventCallback: PageEventCallback = (event) => {
      void this.handlePageEvent(event);
    };
    this.llmPage.onEvent(eventCallback);
    this.toolsPage.onEvent(eventCallback);
    this.motionPage.onEvent(eventCallback);

    this.setupEventListeners();
  }

  /**
   * 获取 DOM 元素
   */
  private getElement<T extends HTMLElement>(selector: string): T {
    const element = document.querySelector<T>(selector);
    if (!element) {
      throw new Error(`设置窗口初始化失败：找不到元素 ${selector}`);
    }
    return element;
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners(): void {
    // 侧边栏导航
    this.sidebar.addEventListener("click", (event) => {
      const target = event.target as HTMLElement | null;
      const tab = target?.closest<HTMLButtonElement>(".settings-tab");
      if (!tab) {
        return;
      }

      const page = tab.dataset.page;
      if (!page || page === this.currentPage) {
        return;
      }

      this.switchPage(page);
    });

    // 最小化按钮
    this.minBtn.addEventListener("click", () => {
      window.desktopPetApi.minimizeCurrentWindow();
    });

    // 关闭按钮
    this.closeBtn.addEventListener("click", () => {
      window.desktopPetApi.closeCurrentWindow();
    });

    // 模型变化监听
    const unsubscribeModelChanged = window.desktopPetApi.onModelChanged?.(() => {
      void this.refreshAfterModelChanged();
    });

    // 模型变换监听
    const unsubscribeTransformChanged = window.desktopPetApi.onModelTransformChanged?.((payload) => {
      this.modelPage.updateTransformData(payload);
    });

    // 页面卸载清理
    window.addEventListener("beforeunload", () => {
      if (typeof unsubscribeTransformChanged === "function") {
        unsubscribeTransformChanged();
      }
      if (typeof unsubscribeModelChanged === "function") {
        unsubscribeModelChanged();
      }
      this.toast.dispose();
    });
  }

  /**
   * 切换页面
   */
  private switchPage(newPage: string): void {
    // 更新当前页面
    this.currentPage = newPage;

    // 更新 UI
    document.querySelectorAll<HTMLButtonElement>(".settings-tab").forEach((item) => {
      item.classList.toggle("active", item.dataset.page === newPage);
    });

    document.querySelectorAll<HTMLDivElement>(".settings-page").forEach((item) => {
      item.classList.toggle("active", item.dataset.page === newPage);
    });

    // 渲染新页面（只显示已保存状态）
    void this.renderPage(newPage);
  }

  /**
   * 渲染页面
   */
  private async renderPage(pageName: string): Promise<void> {
    if (!this.savedState) {
      return;
    }

    const page = this.pages.get(pageName);
    if (!page) {
      // model 页面特殊处理
      if (pageName === "model") {
        void this.modelPage.refreshModelConfig();
      } else if (pageName === "multimodal") {
        void this.multimodalPage.render();
      }
      return;
    }

    const renderData: PageRenderData = {
      saved: this.savedState,
      dependencies: await this.getPageDependencies(pageName),
    };

    page.render(renderData);
  }

  /**
   * 获取页面依赖数据
   */
  private async getPageDependencies(pageName: string): Promise<PageRenderData["dependencies"]> {
    const deps: PageRenderData["dependencies"] = {};

    if (pageName === "llm" || pageName === "motion") {
      deps.expressionLabels = this.getExpressionLabels();
    }

    if (pageName === "motion") {
      deps.modelConfig = this.modelConfig || undefined;
      if (this.modelConfig) {
        const activeModel = this.modelConfig.models.find(
          (m) => m.id === this.modelConfig!.activeModelId
        );
        if (activeModel) {
          deps.availableMotions = await this.loadMotionsFromModel(
            activeModel.modelUrl || activeModel.entry || ""
          );
        }
      }
    }

    if (pageName === "tools") {
      try {
        const result = await window.desktopPetApi.getAvailableTools();
        deps.availableTools = result.tools;
      } catch (error) {
        this.toast.error(appendErrorMessage("读取工具列表失败", error));
        deps.availableTools = [];
      }
    }

    return deps;
  }

  /**
   * 从模型加载动作列表
   */
  private async loadMotionsFromModel(modelUrl: string): Promise<string[]> {
    if (!modelUrl) {
      return [];
    }
    try {
      const response = await fetch(modelUrl);
      if (!response.ok) {
        return [];
      }
      const model3Json = await response.json();
      const motions = model3Json.FileReferences?.Motions;
      if (!motions) {
        return [];
      }
      return Object.keys(motions);
    } catch {
      return [];
    }
  }

  /**
   * 获取表情标签列表（从已保存状态）
   */
  private getExpressionLabels(): string[] {
    if (this.modelConfig) {
      const activeModel = this.modelConfig.models.find(
        (m) => m.id === this.modelConfig!.activeModelId
      );
      if (activeModel?.motionConfig) {
        return activeModel.motionConfig
          .filter((c) => c.setting === "expression" && c.label)
          .map((c) => c.label!);
      }
    }
    return [];
  }

  /**
   * 处理页面事件
   */
  private async handlePageEvent(event: PageEvent): Promise<void> {
    if (event.type === "submit") {
      await this.handleSubmit(event.page);
    }
  }

  /**
   * 提交保存
   */
  private async handleSubmit(pageName: string): Promise<void> {
    const page = this.pages.get(pageName);
    if (!page || !this.savedState) {
      return;
    }

    // 获取当前表单数据
    const editingData = page.getEditingData();

    try {
      if (pageName === "llm" && editingData.llm) {
        await this.saveLlmSettings(editingData.llm);
      } else if (pageName === "motion" && editingData.motion) {
        await this.saveMotionSettings(editingData.motion);
      } else if (pageName === "tools" && editingData.tools) {
        await this.saveToolsSettings(editingData.tools);
      } else {
        return;
      }

      this.toast.success("修改成功");
      await this.renderPage(pageName);
    } catch (error) {
      this.toast.error(appendErrorMessage("修改失败", error));
    }
  }

  /**
   * 保存 LLM 设置
   */
  private async saveLlmSettings(llmData: NonNullable<EditingState["llm"]>): Promise<void> {
    if (!this.savedState) {
      return;
    }

    // 构建系统提示词
    const expressionLabels = this.getExpressionLabels();
    const system_prompt = this.buildSystemPrompt(llmData, expressionLabels);

    const newState: ChatSettingsState = {
      ...this.savedState,
      openai_base_url: llmData.openai_base_url,
      openai_api_key: llmData.openai_api_key,
      model_name: llmData.model_name,
      temperature: llmData.temperature,
      system_prompt,
      name: llmData.name || undefined,
      feature: llmData.feature || undefined,
      character: llmData.character || undefined,
      address: llmData.address || undefined,
      characteristic: llmData.characteristic || undefined,
      constraint: llmData.constraint || undefined,
    };

    await window.desktopPetApi.updateChatSettings(newState);
    this.savedState = newState;
  }

  /**
   * 保存动作设置
   */
  private async saveMotionSettings(motionData: NonNullable<EditingState["motion"]>): Promise<void> {
    if (!this.modelConfig) {
      throw new Error("模型配置尚未加载");
    }

    const activeModelId = this.modelConfig.activeModelId;
    const motionConfigs = motionData.motionConfigs;

    // 保存动作配置
    await window.desktopPetApi.updateModelMotionConfig?.({
      modelId: activeModelId,
      motionConfig: motionConfigs,
    });

    // 重新获取模型配置
    this.modelConfig = await window.desktopPetApi.getModelConfig();

    // 更新系统提示词
    if (this.savedState) {
      const expressionLabels = this.getExpressionLabels();
      const system_prompt = this.buildSystemPromptFromSaved(expressionLabels);

      const newState: ChatSettingsState = {
        ...this.savedState,
        system_prompt,
      };

      await window.desktopPetApi.updateChatSettings(newState);
      this.savedState = newState;
    }
  }

  /**
   * 保存工具设置
   */
  private async saveToolsSettings(toolsData: NonNullable<EditingState["tools"]>): Promise<void> {
    if (!this.savedState) {
      return;
    }

    const newState: ChatSettingsState = {
      ...this.savedState,
      tools_list: toolsData.tools_list,
    };

    await window.desktopPetApi.updateChatSettings(newState);
    this.savedState = newState;
  }

  /**
   * 构建系统提示词
   */
  private buildSystemPrompt(
    llmData: NonNullable<EditingState["llm"]>,
    expressionLabels: string[]
  ): string {
    const name = llmData.name || "日和";
    const feature = llmData.feature || "可爱";
    const character = llmData.character || "AI少女";
    const address = llmData.address || "主人";

    let prompt = `你是${name}，一个${feature}的${character}，称呼用户为${address}。`;
    if (llmData.characteristic) {
      prompt += `\n${llmData.characteristic}`;
    }
    if (llmData.constraint) {
      prompt += `\n${llmData.constraint}`;
    }

    if (expressionLabels.length > 0) {
      const tagsList = expressionLabels.map((l) => `<${l}>`).join("");
      prompt += `\n你可以在对话中使用以下表情标签:${tagsList}使用时必须像示例一样使用尖括号<>包裹`;
    }

    return prompt;
  }

  /**
   * 从已保存状态构建系统提示词
   */
  private buildSystemPromptFromSaved(expressionLabels: string[]): string {
    if (!this.savedState) {
      return "";
    }

    const name = this.savedState.name || "日和";
    const feature = this.savedState.feature || "可爱";
    const character = this.savedState.character || "AI少女";
    const address = this.savedState.address || "主人";

    let prompt = `你是${name}，一个${feature}的${character}，称呼用户为${address}。`;
    if (this.savedState.characteristic) {
      prompt += `\n${this.savedState.characteristic}`;
    }
    if (this.savedState.constraint) {
      prompt += `\n${this.savedState.constraint}`;
    }

    if (expressionLabels.length > 0) {
      const tagsList = expressionLabels.map((l) => `<${l}>`).join("");
      prompt += `\n你可以在对话中使用以下表情标签:${tagsList}使用时必须像示例一样使用尖括号<>包裹`;
    }

    return prompt;
  }

  /**
   * 初始化聊天设置
   */
  private async initChatSettings(clearCurrent = false): Promise<boolean> {
    if (clearCurrent) {
      this.savedState = null;
    }
    try {
      this.savedState = await window.desktopPetApi.getChatSettings();
      return true;
    } catch (error) {
      this.toast.error(appendErrorMessage("读取聊天设置失败", error));
      return false;
    }
  }

  /**
   * 模型变化后刷新
   */
  private async refreshAfterModelChanged(): Promise<void> {
    await Promise.all([this.modelPage.refreshModelConfig(), this.initChatSettings(true)]);
    // 获取最新的模型配置
    this.modelConfig = await window.desktopPetApi.getModelConfig();
    // 渲染当前页面
    await this.renderPage(this.currentPage);
  }

  /**
   * 初始化
   */
  async init(): Promise<void> {
    await Promise.all([
      this.modelPage.refreshModelConfig(),
      this.initChatSettings(),
      this.multimodalPage.render(),
    ]);

    // 获取模型配置
    this.modelConfig = await window.desktopPetApi.getModelConfig();

    // 渲染初始页面
    await this.renderPage(this.currentPage);
  }
}

// 启动应用
void new SettingsApp().init();
