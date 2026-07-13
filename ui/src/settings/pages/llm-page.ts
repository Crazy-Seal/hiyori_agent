/**
 * LLM 配置页面
 */

import type {
  ISettingsPage,
  PageRenderData,
  PageEditingData,
  PageEventCallback,
} from "../types.js";
import { bindPressToRevealSecret } from "../components/press-to-reveal-secret.js";

/**
 * LLM 配置页面管理器（纯视图组件）
 */
export class LlmPage implements ISettingsPage {
  private baseUrlInput: HTMLInputElement;
  private apiKeyInput: HTMLInputElement;
  private modelNameInput: HTMLInputElement;
  private temperatureInput: HTMLInputElement;
  private systemPromptInput: HTMLTextAreaElement;
  private confirmBtn: HTMLButtonElement;

  // 提示词模板字段
  private nameInput: HTMLInputElement;
  private featureInput: HTMLInputElement;
  private characterInput: HTMLInputElement;
  private addressInput: HTMLInputElement;
  private characteristicInput: HTMLTextAreaElement;
  private constraintInput: HTMLTextAreaElement;

  private eventCallback?: PageEventCallback;

  /** 表情标签列表（从 motion 配置获取） */
  private expressionLabels: string[] = [];

  constructor(
    baseUrlInput: HTMLInputElement,
    apiKeyInput: HTMLInputElement,
    apiKeyRevealButton: HTMLButtonElement,
    modelNameInput: HTMLInputElement,
    temperatureInput: HTMLInputElement,
    systemPromptInput: HTMLTextAreaElement,
    confirmBtn: HTMLButtonElement,
    nameInput: HTMLInputElement,
    featureInput: HTMLInputElement,
    characterInput: HTMLInputElement,
    addressInput: HTMLInputElement,
    characteristicInput: HTMLTextAreaElement,
    constraintInput: HTMLTextAreaElement
  ) {
    this.baseUrlInput = baseUrlInput;
    this.apiKeyInput = apiKeyInput;
    bindPressToRevealSecret(this.apiKeyInput, apiKeyRevealButton);
    this.modelNameInput = modelNameInput;
    this.temperatureInput = temperatureInput;
    this.systemPromptInput = systemPromptInput;
    this.confirmBtn = confirmBtn;
    this.nameInput = nameInput;
    this.featureInput = featureInput;
    this.characterInput = characterInput;
    this.addressInput = addressInput;
    this.characteristicInput = characteristicInput;
    this.constraintInput = constraintInput;

    this.setupEventListeners();
  }

  /**
   * 设置事件回调
   */
  onEvent(callback: PageEventCallback): void {
    this.eventCallback = callback;
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners(): void {
    // 提示词模板字段变化时更新预览
    [
      this.nameInput,
      this.featureInput,
      this.characterInput,
      this.addressInput,
      this.characteristicInput,
      this.constraintInput,
    ].forEach((input) => {
      input.addEventListener("input", () => {
        this.updateSystemPromptPreview();
      });
    });

    // 确认按钮
    this.confirmBtn.addEventListener("click", () => {
      this.eventCallback?.({ type: "submit", page: "llm" });
    });
  }

  /**
   * 渲染页面
   */
  render(data: PageRenderData): void {
    // 保存表情标签列表
    this.expressionLabels = data.dependencies?.expressionLabels || [];

    // 只使用已保存状态
    const llmData = {
      openai_base_url: data.saved.openai_base_url,
      openai_api_key: data.saved.openai_api_key,
      model_name: data.saved.model_name,
      temperature: data.saved.temperature,
      name: data.saved.name || "",
      feature: data.saved.feature || "",
      character: data.saved.character || "",
      address: data.saved.address || "",
      characteristic: data.saved.characteristic || "",
      constraint: data.saved.constraint || "",
    };

    // 渲染表单
    this.baseUrlInput.value = llmData.openai_base_url;
    this.apiKeyInput.value = llmData.openai_api_key;
    this.modelNameInput.value = llmData.model_name;
    this.temperatureInput.value = String(llmData.temperature);

    // 渲染提示词模板字段
    this.nameInput.value = llmData.name;
    this.featureInput.value = llmData.feature;
    this.characterInput.value = llmData.character;
    this.addressInput.value = llmData.address;
    this.characteristicInput.value = llmData.characteristic;
    this.constraintInput.value = llmData.constraint;

    // 更新系统提示词预览
    this.updateSystemPromptPreview();
  }

  /**
   * 获取当前编辑数据
   */
  getEditingData(): PageEditingData {
    return {
      llm: {
        openai_base_url: this.baseUrlInput.value.trim(),
        openai_api_key: this.apiKeyInput.value.trim(),
        model_name: this.modelNameInput.value.trim(),
        temperature: Number.isFinite(Number(this.temperatureInput.value))
          ? Number(this.temperatureInput.value)
          : 0.7,
        name: this.nameInput.value.trim(),
        feature: this.featureInput.value.trim(),
        character: this.characterInput.value.trim(),
        address: this.addressInput.value.trim(),
        characteristic: this.characteristicInput.value.trim(),
        constraint: this.constraintInput.value.trim(),
      },
    };
  }

  /**
   * 根据模板字段拼装系统提示词
   */
  private buildSystemPrompt(): string {
    const name = this.nameInput.value.trim() || "日和";
    const feature = this.featureInput.value.trim() || "可爱";
    const character = this.characterInput.value.trim() || "AI少女";
    const address = this.addressInput.value.trim() || "主人";
    const characteristic = this.characteristicInput.value.trim();
    const constraint = this.constraintInput.value.trim();

    let prompt = `你是${name}，一个${feature}的${character}，称呼用户为${address}。`;
    if (characteristic) {
      prompt += `\n${characteristic}`;
    }
    if (constraint) {
      prompt += `\n${constraint}`;
    }

    // 添加表情标签说明
    if (this.expressionLabels.length > 0) {
      const tagsList = this.expressionLabels.map((l) => `<${l}>`).join("");
      prompt += `\n你可以在对话中使用以下表情标签:${tagsList}使用时必须像示例一样使用尖括号<>包裹`;
    }

    return prompt;
  }

  /**
   * 更新系统提示词预览
   */
  private updateSystemPromptPreview(): void {
    this.systemPromptInput.value = this.buildSystemPrompt();
  }
}
