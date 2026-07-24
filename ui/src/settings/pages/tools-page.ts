/**
 * 工具配置页面
 */

import type {
  ChatSettingsState,
  ToolItem,
  ISettingsPage,
  PageRenderData,
  PageEditingData,
  PageEventCallback,
} from "../types.js";

/**
 * 工具配置页面管理器（纯视图组件）
 */
export class ToolsPage implements ISettingsPage {
  private toolsTableBody: HTMLTableSectionElement;
  private toolsEmpty: HTMLDivElement;
  private confirmBtn: HTMLButtonElement;

  private eventCallback?: PageEventCallback;

  constructor(
    toolsTableBody: HTMLTableSectionElement,
    toolsEmpty: HTMLDivElement,
    confirmBtn: HTMLButtonElement
  ) {
    this.toolsTableBody = toolsTableBody;
    this.toolsEmpty = toolsEmpty;
    this.confirmBtn = confirmBtn;

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
    this.confirmBtn.addEventListener("click", () => {
      this.eventCallback?.({ type: "submit", page: "tools" });
    });
  }

  /**
   * 渲染页面
   */
  render(data: PageRenderData): void {
    // 获取可用工具列表
    const availableTools = data.dependencies?.availableTools || [];

    // 获取选中的工具列表（只使用已保存状态）
    const selectedTools = data.saved.tools_list;

    this.renderToolsTable(availableTools, selectedTools);
  }

  /**
   * 获取当前编辑数据
   */
  getEditingData(): PageEditingData {
    return {
      tools: {
        tools_list: this.collectSelectedTools(),
      },
    };
  }

  /**
   * 渲染工具表格
   */
  private renderToolsTable(tools: ToolItem[], selectedTools: string[]): void {
    this.toolsTableBody.innerHTML = "";

    if (tools.length === 0) {
      this.toolsEmpty.hidden = false;
      return;
    }

    this.toolsEmpty.hidden = true;
    for (const tool of tools) {
      const row = document.createElement("tr");

      const checkCell = document.createElement("td");
      checkCell.className = "col-check";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "ui-checkbox";
      checkbox.dataset.toolName = tool.name;
      checkbox.checked = selectedTools.includes(tool.name);
      checkCell.appendChild(checkbox);

      const nameCell = document.createElement("td");
      nameCell.textContent = tool.name;

      row.appendChild(checkCell);
      row.appendChild(nameCell);
      this.toolsTableBody.appendChild(row);
    }
  }

  /**
   * 收集选中的工具
   */
  private collectSelectedTools(): string[] {
    const selected: string[] = [];
    this.toolsTableBody.querySelectorAll<HTMLInputElement>('input[type="checkbox"][data-tool-name]').forEach((input) => {
      if (input.checked && input.dataset.toolName) {
        selected.push(input.dataset.toolName);
      }
    });
    return selected;
  }
}
