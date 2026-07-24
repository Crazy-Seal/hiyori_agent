/**
 * 表情控制页面
 */

import type {
  MotionConfig,
  MotionSettingType,
  ISettingsPage,
  PageRenderData,
  PageEditingData,
  PageEventCallback,
  ChatSettingsState,
} from "../types.js";

/**
 * Model3.json 结构中的动作定义
 */
type Model3MotionGroup = Array<{ File: string }>;

type Model3FileReferences = {
  Moc?: string;
  Textures?: string[];
  Motions?: Record<string, Model3MotionGroup>;
};

type Model3Json = {
  Version: number;
  FileReferences: Model3FileReferences;
};

/**
 * 表情控制页面管理器（纯视图组件）
 */
export class MotionPage implements ISettingsPage {
  private motionTableBody: HTMLTableSectionElement;
  private motionEmpty: HTMLDivElement;
  private confirmBtn: HTMLButtonElement;
  private systemPromptPreview: HTMLTextAreaElement;

  private eventCallback?: PageEventCallback;

  // 当前渲染的动作列表（从 dependencies 获取）
  private availableMotions: string[] = [];

  // 已保存的状态（用于预览）
  private savedState: ChatSettingsState | null = null;

  constructor(
    motionTableBody: HTMLTableSectionElement,
    motionEmpty: HTMLDivElement,
    confirmBtn: HTMLButtonElement,
    systemPromptPreview: HTMLTextAreaElement
  ) {
    this.motionTableBody = motionTableBody;
    this.motionEmpty = motionEmpty;
    this.confirmBtn = confirmBtn;
    this.systemPromptPreview = systemPromptPreview;

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
    // 保存按钮
    this.confirmBtn.addEventListener("click", () => {
      this.eventCallback?.({ type: "submit", page: "motion" });
    });

    // 表格事件委托
    this.motionTableBody.addEventListener("click", (event) => {
      const target = event.target as HTMLElement;
      const previewBtn = target.closest<HTMLButtonElement>(".motion-preview-btn");
      if (previewBtn) {
        const motionName = previewBtn.dataset.motionName;
        if (motionName) {
          this.previewMotion(motionName);
        }
      }
    });

    // 设置下拉框变化
    this.motionTableBody.addEventListener("change", (event) => {
      const target = event.target as HTMLElement;
      if (target.classList.contains("motion-setting-select")) {
        const motionName = target.dataset.motionName;
        const value = (target as HTMLSelectElement).value as MotionSettingType;
        if (motionName) {
          this.handleSettingChange(motionName, value);
        }
      }
    });

    // 标签输入变化
    this.motionTableBody.addEventListener("input", (event) => {
      const target = event.target as HTMLElement;
      if (target.classList.contains("motion-label-input")) {
        const motionName = target.dataset.motionName;
        const value = (target as HTMLInputElement).value;
        if (motionName) {
          this.handleLabelChange(motionName, value);
        }
      }
    });
  }

  /**
   * 渲染页面
   */
  render(data: PageRenderData): void {
    // 保存已保存状态
    this.savedState = data.saved;

    // 获取可用动作列表
    this.availableMotions = data.dependencies?.availableMotions || [];

    // 获取动作配置（只使用已保存状态）
    let motionConfigs: MotionConfig[];
    if (data.dependencies?.modelConfig) {
      const activeModel = data.dependencies.modelConfig.models.find(
        (m) => m.id === data.dependencies!.modelConfig!.activeModelId
      );
      motionConfigs = activeModel?.motionConfig || this.createDefaultMotionConfigs();
    } else {
      motionConfigs = this.createDefaultMotionConfigs();
    }

    // 渲染表格
    this.renderMotionTable(motionConfigs);

    // 更新系统提示词预览
    this.updateSystemPromptPreview(data.saved, motionConfigs);
  }

  /**
   * 创建默认动作配置
   */
  private createDefaultMotionConfigs(): MotionConfig[] {
    return this.availableMotions.map((name) => ({
      motionName: name,
      setting: name.toLowerCase() === "idle" ? ("idle" as const) : ("none" as const),
    }));
  }

  /**
   * 获取当前编辑数据
   */
  getEditingData(): PageEditingData {
    return {
      motion: {
        motionConfigs: this.collectMotionConfigs(),
      },
    };
  }

  /**
   * 收集表格中的动作配置
   */
  private collectMotionConfigs(): MotionConfig[] {
    const configs: MotionConfig[] = [];
    this.motionTableBody.querySelectorAll<HTMLSelectElement>(".motion-setting-select").forEach((select) => {
      const motionName = select.dataset.motionName;
      if (motionName) {
        const setting = select.value as MotionSettingType;
        const labelInput = this.motionTableBody.querySelector<HTMLInputElement>(
          `.motion-label-input[data-motion-name="${motionName}"]`
        );
        const label = labelInput?.value.trim() || undefined;

        configs.push({
          motionName,
          setting,
          label: setting === "expression" ? label : undefined,
        });
      }
    });
    return configs;
  }

  /**
   * 处理设置变化
   */
  private handleSettingChange(motionName: string, setting: MotionSettingType): void {
    // 如果设置为 idle，清除其他 idle
    if (setting === "idle") {
      this.motionTableBody.querySelectorAll<HTMLSelectElement>(".motion-setting-select").forEach((select) => {
        if (select.dataset.motionName !== motionName && select.value === "idle") {
          select.value = "none";
        }
      });
    }

    // 更新标签输入框状态
    const labelInput = this.motionTableBody.querySelector<HTMLInputElement>(
      `.motion-label-input[data-motion-name="${motionName}"]`
    );
    if (labelInput) {
      labelInput.disabled = setting !== "expression";
      labelInput.placeholder = setting === "expression" ? "输入标签" : "-";
      if (setting !== "expression") {
        labelInput.value = "";
      }
    }
  }

  /**
   * 处理标签变化
   */
  private handleLabelChange(motionName: string, label: string): void {
    // 标签变化时更新预览
    const motionConfigs = this.collectMotionConfigs();
    // 使用已保存的状态更新预览
    if (this.savedState) {
      this.updateSystemPromptPreview(this.savedState, motionConfigs);
    }
  }

  /**
   * 预览动作
   */
  private previewMotion(motionName: string): void {
    window.desktopPetApi.playMotion?.(motionName);
  }

  /**
   * 渲染动作表格
   */
  private renderMotionTable(motionConfigs: MotionConfig[]): void {
    this.motionTableBody.innerHTML = "";

    if (this.availableMotions.length === 0) {
      this.motionEmpty.hidden = false;
      return;
    }

    this.motionEmpty.hidden = true;

    for (const motionName of this.availableMotions) {
      const config = motionConfigs.find((c) => c.motionName === motionName) || {
        motionName,
        setting: "none" as const,
      };

      const row = document.createElement("tr");

      // 动作名称
      const nameCell = document.createElement("td");
      nameCell.className = "col-name";
      nameCell.textContent = motionName;

      // 标签输入（仅 expression 类型可编辑）
      const labelCell = document.createElement("td");
      labelCell.className = "col-label";
      const labelInput = document.createElement("input");
      labelInput.type = "text";
      labelInput.className = "motion-label-input ui-control ui-control--small";
      labelInput.dataset.motionName = motionName;
      labelInput.value = config.label || "";
      labelInput.disabled = config.setting !== "expression";
      labelInput.placeholder = config.setting === "expression" ? "输入标签" : "-";
      labelCell.appendChild(labelInput);

      // 预览按钮
      const previewCell = document.createElement("td");
      previewCell.className = "col-preview";
      const previewBtn = document.createElement("button");
      previewBtn.type = "button";
      previewBtn.className = "motion-preview-btn ui-button ui-button--secondary ui-button--small";
      previewBtn.dataset.motionName = motionName;
      previewBtn.textContent = "播放";
      previewCell.appendChild(previewBtn);

      // 设置下拉框
      const settingCell = document.createElement("td");
      settingCell.className = "col-setting";
      const select = document.createElement("select");
      select.className = "motion-setting-select ui-control ui-control--small ui-select";
      select.dataset.motionName = motionName;
      select.ariaLabel = `${motionName} 的动作设置`;

      const options = [
        { value: "none", text: "无" },
        { value: "idle", text: "空闲" },
        { value: "expression", text: "表情" },
      ];

      for (const opt of options) {
        const option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.text;
        option.selected = config.setting === opt.value;
        select.appendChild(option);
      }

      settingCell.appendChild(select);

      row.appendChild(nameCell);
      row.appendChild(labelCell);
      row.appendChild(previewCell);
      row.appendChild(settingCell);
      this.motionTableBody.appendChild(row);
    }
  }

  /**
   * 更新系统提示词预览
   */
  private updateSystemPromptPreview(saved: PageRenderData["saved"], motionConfigs: MotionConfig[]): void {
    const name = saved.name || "日和";
    const feature = saved.feature || "可爱";
    const character = saved.character || "AI少女";
    const address = saved.address || "主人";
    const characteristic = saved.characteristic || "";
    const constraint = saved.constraint || "";

    let prompt = `你是${name}，一个${feature}的${character}，称呼用户为${address}。`;
    if (characteristic) {
      prompt += `\n${characteristic}`;
    }
    if (constraint) {
      prompt += `\n${constraint}`;
    }

    // 添加表情标签说明
    const expressionLabels = motionConfigs
      .filter((c) => c.setting === "expression" && c.label)
      .map((c) => c.label!);

    if (expressionLabels.length > 0) {
      const tagsList = expressionLabels.map((l) => `<${l}>`).join("");
      prompt += `\n你可以在对话中使用以下表情标签:${tagsList}使用时必须像示例一样使用尖括号<>包裹`;
    }

    this.systemPromptPreview.value = prompt;
  }
}
