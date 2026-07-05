/**
 * 设置窗口类型定义
 */

// 从共享类型导入并重新导出
import type {
  ChatSettingsData,
  FrontendSettings as SharedFrontendSettings,
  ImportPreview as SharedImportPreview,
  ModelConfigView,
  ModelTransformData as SharedModelTransformData,
  MotionConfig as SharedMotionConfig,
  MotionSettingType as SharedMotionSettingType,
  ToolItem as SharedToolItem,
} from "../../shared-types.js";

export type MotionConfig = SharedMotionConfig;
export type MotionSettingType = SharedMotionSettingType;

/**
 * 模型配置
 */
export type ModelConfig = ModelConfigView;

/**
 * 导入预览
 */
export type ImportPreview = SharedImportPreview;

/**
 * 聊天设置状态
 */
export type ChatSettingsState = ChatSettingsData;

/**
 * 工具项
 */
export type ToolItem = SharedToolItem;

/**
 * 前端设置
 */
export type FrontendSettings = SharedFrontendSettings;

/**
 * 模型变换数据
 */
export type ModelTransformData = SharedModelTransformData;

/**
 * 编辑状态（每个页面独立的编辑数据）
 */
export interface EditingState {
  llm?: {
    openai_base_url: string;
    openai_api_key: string;
    model_name: string;
    temperature: number;
    name: string;
    feature: string;
    character: string;
    address: string;
    characteristic: string;
    constraint: string;
  };
  motion?: {
    motionConfigs: MotionConfig[];
  };
  tools?: {
    tools_list: string[];
  };
}

/**
 * 页面渲染数据
 */
export interface PageRenderData {
  /** 来自已保存状态 */
  saved: ChatSettingsState;
  /** 来自编辑状态（优先使用） */
  editing?: EditingState;
  /** 其他依赖数据 */
  dependencies?: {
    modelConfig?: ModelConfig;
    availableMotions?: string[];
    availableTools?: ToolItem[];
    expressionLabels?: string[];
  };
}

/**
 * 页面编辑数据（由 getEditingData 返回）
 */
export interface PageEditingData {
  llm?: EditingState["llm"];
  motion?: EditingState["motion"];
  tools?: EditingState["tools"];
}

/**
 * 页面事件类型
 */
export type PageEventType = "submit";

/**
 * 页面事件回调参数
 */
export interface PageEvent {
  type: PageEventType;
  page: string;
}

/**
 * 页面事件回调类型
 */
export type PageEventCallback = (event: PageEvent) => void;

/**
 * 设置页面接口（纯视图组件）
 */
export interface ISettingsPage {
  /**
   * 渲染页面
   * @param data 渲染数据（来自 editingState 或 savedState）
   */
  render(data: PageRenderData): void;

  /**
   * 获取当前编辑数据
   * 用于切换页面前保存编辑状态
   */
  getEditingData(): PageEditingData;

  /**
   * 设置事件回调
   */
  onEvent(callback: PageEventCallback): void;
}
