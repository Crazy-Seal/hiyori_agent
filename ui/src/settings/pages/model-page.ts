/**
 * 模型管理页面
 */

import type { ModelConfig, ImportPreview } from "../types.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import {
  appendErrorMessage,
  type SettingsNotifier,
} from "../components/settings-toast.js";

/**
 * 模型管理页面管理器
 */
export class ModelPage {
  private modelList: HTMLDivElement;
  private importPreview: HTMLDivElement;
  private previewName: HTMLDivElement;
  private previewType: HTMLDivElement;
  private previewEntry: HTMLDivElement;
  private confirmImportBtn: HTMLButtonElement;
  private cancelImportBtn: HTMLButtonElement;
  private importModelBtn: HTMLButtonElement;
  private offsetXSlider: HTMLInputElement;
  private offsetYSlider: HTMLInputElement;
  private offsetXValue: HTMLSpanElement;
  private offsetYValue: HTMLSpanElement;
  private followCursorCheckbox: HTMLInputElement;
  private confirmDialog: ConfirmDialog;

  private currentConfig: ModelConfig | null = null;
  private pendingImport: ImportPreview | null = null;
  private syncingSliders = false;

  constructor(
    modelList: HTMLDivElement,
    importPreview: HTMLDivElement,
    previewName: HTMLDivElement,
    previewType: HTMLDivElement,
    previewEntry: HTMLDivElement,
    confirmImportBtn: HTMLButtonElement,
    cancelImportBtn: HTMLButtonElement,
    importModelBtn: HTMLButtonElement,
    offsetXSlider: HTMLInputElement,
    offsetYSlider: HTMLInputElement,
    offsetXValue: HTMLSpanElement,
    offsetYValue: HTMLSpanElement,
    followCursorCheckbox: HTMLInputElement,
    confirmDialog: ConfirmDialog,
    private readonly notifier: SettingsNotifier
  ) {
    this.modelList = modelList;
    this.importPreview = importPreview;
    this.previewName = previewName;
    this.previewType = previewType;
    this.previewEntry = previewEntry;
    this.confirmImportBtn = confirmImportBtn;
    this.cancelImportBtn = cancelImportBtn;
    this.importModelBtn = importModelBtn;
    this.offsetXSlider = offsetXSlider;
    this.offsetYSlider = offsetYSlider;
    this.offsetXValue = offsetXValue;
    this.offsetYValue = offsetYValue;
    this.followCursorCheckbox = followCursorCheckbox;
    this.confirmDialog = confirmDialog;

    this.setupEventListeners();
  }

  /**
   * 设置事件监听
   */
  private setupEventListeners(): void {
    // 导入模型按钮
    this.importModelBtn.addEventListener("click", async () => {
      const preview = await window.desktopPetApi.previewLive2DImport();
      if (!preview) {
        return;
      }

      this.pendingImport = preview;
      this.previewName.textContent = `模型名：${preview.suggestedName}`;
      this.previewType.textContent = "来源类型：文件夹";
      this.previewEntry.textContent = `识别入口：${preview.entryRelativePath}`;
      this.importPreview.hidden = false;
    });

    // 确认导入
    this.confirmImportBtn.addEventListener("click", async () => {
      if (!this.pendingImport) {
        return;
      }

      await window.desktopPetApi.importLive2DModel({
        selectedPath: this.pendingImport.selectedPath,
        suggestedName: this.pendingImport.suggestedName,
      });
      this.clearImportPreview();
      await this.refreshAfterModelChanged();
    });

    // 取消导入
    this.cancelImportBtn.addEventListener("click", () => {
      this.clearImportPreview();
    });

    // 模型列表点击
    this.modelList.addEventListener("click", async (event) => {
      const target = event.target as HTMLElement | null;
      const deleteBtn = target?.closest<HTMLButtonElement>(".delete-model-btn");
      if (deleteBtn) {
        const modelId = deleteBtn.dataset.modelId;
        if (!modelId || deleteBtn.disabled) {
          return;
        }

        const confirmed = await this.confirmDialog.open();
        if (!confirmed) {
          return;
        }

        try {
          await window.desktopPetApi.deleteModel(modelId);
          await this.refreshAfterModelChanged();
          this.notifier.success("模型及配置删除成功");
        } catch (error) {
          this.notifier.error(appendErrorMessage("模型及配置删除失败", error));
        }
        return;
      }

      const item = target?.closest<HTMLButtonElement>(".model-item");
      if (!item) {
        return;
      }

      const modelId = item.dataset.modelId;
      if (!modelId || this.currentConfig?.activeModelId === modelId) {
        return;
      }

      await window.desktopPetApi.setActiveModel(modelId);
      await this.refreshAfterModelChanged();
    });

    // 滑块变化
    this.offsetXSlider.addEventListener("input", () => {
      void this.updateActiveModelTransform();
    });

    this.offsetYSlider.addEventListener("input", () => {
      void this.updateActiveModelTransform();
    });

    this.followCursorCheckbox.addEventListener("change", () => {
      void this.updateActiveModelTransform();
    });
  }

  /**
   * 清除导入预览
   */
  private clearImportPreview(): void {
    this.pendingImport = null;
    this.previewName.textContent = "";
    this.previewType.textContent = "";
    this.previewEntry.textContent = "";
    this.importPreview.hidden = true;
  }

  /**
   * 更新激活模型的变换
   */
  private async updateActiveModelTransform(): Promise<void> {
    if (!this.currentConfig || this.syncingSliders) {
      return;
    }

    const modelId = this.currentConfig.activeModelId;
    const offsetX = Number(this.offsetXSlider.value);
    const offsetY = Number(this.offsetYSlider.value);
    this.offsetXValue.textContent = `${offsetX}`;
    this.offsetYValue.textContent = `${offsetY}`;

    await window.desktopPetApi.updateModelTransform({
      modelId,
      offsetX,
      offsetY,
      followCursor: this.followCursorCheckbox.checked,
    });

    const target = this.currentConfig.models.find((item) => item.id === modelId);
    if (target) {
      target.offsetX = offsetX;
      target.offsetY = offsetY;
      target.followCursor = this.followCursorCheckbox.checked;
    }
  }

  /**
   * 渲染模型列表
   */
  renderModelList(config: ModelConfig): void {
    this.modelList.innerHTML = "";

    for (const model of config.models) {
      const row = document.createElement("div");
      row.className = "model-item-row";

      const button = document.createElement("button");
      button.type = "button";
      button.className = `model-item ui-surface ui-surface--compact ${model.id === config.activeModelId ? "active" : ""}`;
      button.dataset.modelId = model.id;
      button.innerHTML = `<div class="model-name">${model.name}</div><div class="model-session">session_id: ${model.sessionId}</div>`;

      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "delete-model-btn ui-button ui-button--danger ui-button--medium";
      deleteButton.dataset.modelId = model.id;
      deleteButton.textContent = "删除";
      deleteButton.disabled = !model.deletable;

      row.appendChild(button);
      row.appendChild(deleteButton);
      this.modelList.appendChild(row);
    }
  }

  /**
   * 渲染变换滑块
   */
  renderTransformSliders(config: ModelConfig): void {
    const active = config.models.find((item) => item.id === config.activeModelId);
    const offsetX = active?.offsetX ?? 0;
    const offsetY = active?.offsetY ?? 0;
    const followCursor = active?.followCursor ?? true;

    this.syncingSliders = true;
    this.offsetXSlider.value = String(Math.round(offsetX));
    this.offsetYSlider.value = String(Math.round(offsetY));
    this.offsetXValue.textContent = `${Math.round(offsetX)}`;
    this.offsetYValue.textContent = `${Math.round(offsetY)}`;
    this.followCursorCheckbox.checked = followCursor;
    this.syncingSliders = false;
  }

  /**
   * 刷新模型配置
   */
  async refreshModelConfig(): Promise<ModelConfig> {
    const config = await window.desktopPetApi.getModelConfig();
    this.currentConfig = config;
    this.renderModelList(config);
    this.renderTransformSliders(config);
    return config;
  }

  /**
   * 模型变化后刷新
   */
  async refreshAfterModelChanged(): Promise<void> {
    await this.refreshModelConfig();
  }

  /**
   * 获取当前配置
   */
  getCurrentConfig(): ModelConfig | null {
    return this.currentConfig;
  }

  /**
   * 更新配置中的变换数据
   */
  updateTransformData(data: { id: string; offsetX: number; offsetY: number; userScale: number; followCursor: boolean }): void {
    if (!this.currentConfig || data.id !== this.currentConfig.activeModelId) {
      return;
    }

    const target = this.currentConfig.models.find((item) => item.id === data.id);
    if (!target) {
      return;
    }

    target.offsetX = data.offsetX;
    target.offsetY = data.offsetY;
    target.userScale = data.userScale;
    target.followCursor = data.followCursor;
    this.renderTransformSliders(this.currentConfig);
  }
}
