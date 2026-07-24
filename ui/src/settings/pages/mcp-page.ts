import type {
  MCPModelSettings,
  MCPServerConfig,
  MCPServerView,
  MCPToolInfo,
  MCPToolPolicy,
} from "../../../shared-types.js";
import type { ISettingsPage, PageEditingData, PageEventCallback, PageRenderData } from "../types.js";
import type { ConfirmDialog } from "../components/confirm-dialog.js";
import { appendErrorMessage, type SettingsToast } from "../components/settings-toast.js";
import { authorizeBaseUrlChange, classifyHttpEndpoint } from "../url-security.js";
import { buildEnabledServerPolicy, fingerprintMcpConfig } from "../mcp-config.js";

type SecretRow = { key: HTMLInputElement; value: HTMLInputElement; element: HTMLDivElement };

/**
 * 管理 MCP Server 定义和当前模型工具权限的设置页面。
 */
export class McpPage implements ISettingsPage {
  private servers: MCPServerView[] = [];
  private tools = new Map<string, MCPToolInfo[]>();
  private policies: MCPModelSettings = { servers: {} };
  private callback: PageEventCallback | null = null;
  private editingId: string | null = null;
  private testedFingerprint: string | null = null;
  private authorizedInsecureFingerprint: string | null = null;
  private envRows: SecretRow[] = [];
  private headerRows: SecretRow[] = [];

  /**
   * 初始化 MCP 设置页并绑定用户交互事件。
   *
   * @param root - MCP 页面根容器。
   * @param confirmDialog - 通用确认对话框。
   * @param toast - 设置页消息提示器。
   */
  constructor(
    private readonly root: HTMLDivElement,
    private readonly confirmDialog: ConfirmDialog,
    private readonly toast: SettingsToast
  ) {
    this.q<HTMLButtonElement>("#mcp-add-btn").addEventListener("click", () => this.openEditor());
    this.q<HTMLButtonElement>("#mcp-policy-save-btn").addEventListener("click", () =>
      this.callback?.({ type: "submit", page: "mcp" }));
    this.q<HTMLSelectElement>("#mcp-transport").addEventListener("change", () => this.updateTransportFields());
    this.q<HTMLButtonElement>("#mcp-add-env").addEventListener("click", () => this.addSecretRow("env"));
    this.q<HTMLButtonElement>("#mcp-add-header").addEventListener("click", () => this.addSecretRow("header"));
    this.q<HTMLButtonElement>("#mcp-cancel-btn").addEventListener("click", () => this.closeEditor());
    this.q<HTMLButtonElement>("#mcp-test-btn").addEventListener("click", () => void this.testCurrent());
    this.q<HTMLFormElement>("#mcp-editor").addEventListener("submit", (event) => {
      event.preventDefault();
      void this.saveCurrent();
    });
  }

  /**
   * 使用已保存权限和 MCP 依赖数据渲染页面。
   *
   * @param data - 当前设置状态以及 Server、工具目录依赖。
   */
  render(data: PageRenderData): void {
    this.servers = data.dependencies?.mcpServers ?? [];
    this.tools = data.dependencies?.mcpTools ?? new Map();
    this.policies = structuredClone(data.saved.mcp ?? { servers: {} });
    this.renderServers();
  }

  /**
   * 获取当前页面编辑中的模型级 MCP 权限。
   *
   * @returns 可提交给设置管理器的深拷贝数据。
   */
  getEditingData(): PageEditingData {
    return { mcp: structuredClone(this.policies) };
  }

  /**
   * 注册设置页事件回调。
   *
   * @param callback - 接收提交和失效通知的回调函数。
   */
  onEvent(callback: PageEventCallback): void {
    this.callback = callback;
  }

  /**
   * 在 MCP 页面根节点内查询必需元素。
   *
   * @param selector - CSS 选择器。
   * @returns 匹配的页面元素。
   * @throws {Error} 页面结构中不存在指定元素时抛出。
   */
  private q<T extends HTMLElement>(selector: string): T {
    const value = this.root.querySelector<T>(selector);
    if (!value) throw new Error(`MCP 页面缺少元素 ${selector}`);
    return value;
  }

  /**
   * 根据当前 Server 数据重新渲染卡片列表。
   */
  private renderServers(): void {
    const list = this.q<HTMLDivElement>("#mcp-server-list");
    list.replaceChildren();
    this.q<HTMLDivElement>("#mcp-empty").hidden = this.servers.length > 0;
    this.q<HTMLButtonElement>("#mcp-policy-save-btn").hidden = this.servers.length === 0;
    for (const server of this.servers) list.append(this.createServerCard(server));
  }

  /**
   * 创建包含状态、操作和权限面板的 Server 卡片。
   *
   * @param server - 待展示的 MCP Server 视图。
   * @returns 完整的 Server 卡片元素。
   */
  private createServerCard(server: MCPServerView): HTMLDivElement {
    const card = document.createElement("div");
    card.className = "mcp-server-card ui-surface";
    const header = document.createElement("div");
    header.className = "mcp-server-header";
    const title = document.createElement("div");
    title.textContent = `${server.config.name}  ·  ${server.config.transport}`;
    const status = document.createElement("span");
    status.className = `mcp-status mcp-status-${server.runtime.status}`;
    status.textContent = `${server.runtime.status} · ${server.runtime.tool_count} 个工具`;
    header.append(title, status);
    card.append(header);
    if (server.runtime.last_error) {
      const error = document.createElement("div");
      error.className = "mcp-error";
      error.textContent = server.runtime.last_error;
      card.append(error);
    }
    if (server.runtime.instructions) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Server Instructions（仅诊断展示）";
      const instructions = document.createElement("pre");
      instructions.textContent = server.runtime.instructions;
      details.append(summary, instructions);
      card.append(details);
    }
    const actions = document.createElement("div");
    actions.className = "mcp-card-actions";
    actions.append(
      this.actionButton("编辑", () => this.openEditor(server)),
      this.actionButton("测试", () => void this.testSaved(server))
    );
    if (server.config.enabled) {
      actions.append(this.actionButton("重连", () => void this.reconnect(server.config.id)));
    }
    actions.append(
      this.actionButton(
        "删除",
        () => void this.remove(server.config.id, server.config.name),
        "danger",
      ),
    );
    card.append(actions, this.createPolicyPanel(server));
    return card;
  }

  /**
   * 创建当前模型对指定 Server 的工具权限面板。
   *
   * @param server - 权限面板对应的 MCP Server。
   * @returns 包含启用开关和工具策略选择器的元素。
   */
  private createPolicyPanel(server: MCPServerView): HTMLDivElement {
    const panel = document.createElement("div");
    panel.className = "mcp-policy-panel";
    const toggleLabel = document.createElement("label");
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.className = "ui-checkbox";
    toggle.checked = Boolean(this.policies.servers[server.config.id]?.enabled);
    toggleLabel.append(toggle, document.createTextNode("当前模型启用此服务"));
    panel.append(toggleLabel);
    const tools = this.tools.get(server.config.id) ?? [];
    const toolList = document.createElement("div");
    toolList.className = "mcp-tool-policy-list";
    /** 使用当前模型权限重新渲染工具策略选择器。 */
    const renderTools = (): void => {
      toolList.replaceChildren();
      const current = this.policies.servers[server.config.id];
      for (const tool of tools) {
        const row = document.createElement("label");
        row.textContent = tool.name;
        const select = document.createElement("select");
        select.className = "ui-control ui-control--small ui-select";
        for (const value of ["allow", "ask", "deny"] as MCPToolPolicy[]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = value;
          select.append(option);
        }
        select.value = current?.tools[tool.name] ?? "ask";
        select.disabled = !current?.enabled;
        select.addEventListener("change", () => {
          const policy = this.policies.servers[server.config.id];
          if (policy) policy.tools[tool.name] = select.value as MCPToolPolicy;
        });
        row.append(select);
        toolList.append(row);
      }
      if (tools.length === 0) toolList.textContent = "尚未获取工具目录";
    };
    toggle.addEventListener("change", () => {
      if (toggle.checked) {
        this.policies.servers[server.config.id] = buildEnabledServerPolicy(
          this.policies.servers[server.config.id], tools.map((tool) => tool.name)
        );
      } else {
        const current = this.policies.servers[server.config.id];
        this.policies.servers[server.config.id] = {
          ...current,
          enabled: false,
          tools: current?.tools ?? {},
        };
      }
      renderTools();
    });
    panel.append(toolList);
    renderTools();
    return panel;
  }

  /**
   * 创建统一样式和行为的操作按钮。
   *
   * @param label - 按钮显示文本。
   * @param action - 点击按钮时执行的操作。
   * @returns 已绑定点击事件的按钮元素。
   */
  private actionButton(
    label: string,
    action: () => void,
    variant: "secondary" | "danger" = "secondary",
  ): HTMLButtonElement {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `ui-button ui-button--${variant} ui-button--small`;
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  }

  /**
   * 打开新增或编辑 MCP Server 的表单。
   *
   * @param server - 可选的已有 Server；未提供时进入新增模式。
   */
  private openEditor(server?: MCPServerView): void {
    this.editingId = server?.config.id ?? null;
    this.testedFingerprint = server?.runtime.status === "available"
      ? fingerprintMcpConfig(server.config)
      : null;
    this.authorizedInsecureFingerprint = null;
    this.q<HTMLFormElement>("#mcp-editor").hidden = false;
    this.q<HTMLElement>("#mcp-editor-title").textContent = server ? "编辑 MCP 服务" : "添加 MCP 服务";
    this.q<HTMLInputElement>("#mcp-id").value = server?.config.id ?? "";
    this.q<HTMLInputElement>("#mcp-id").disabled = Boolean(server);
    this.q<HTMLInputElement>("#mcp-name").value = server?.config.name ?? "";
    this.q<HTMLInputElement>("#mcp-enabled").checked = server?.config.enabled ?? false;
    this.q<HTMLInputElement>("#mcp-connect-timeout").value = String(server?.config.connect_timeout_seconds ?? 15);
    this.q<HTMLInputElement>("#mcp-call-timeout").value = String(server?.config.call_timeout_seconds ?? 60);
    this.q<HTMLSelectElement>("#mcp-transport").value = server?.config.transport ?? "stdio";
    this.q<HTMLInputElement>("#mcp-command").value = server?.config.transport === "stdio" ? server.config.command : "";
    this.q<HTMLTextAreaElement>("#mcp-args").value = server?.config.transport === "stdio" ? server.config.args.join("\n") : "";
    this.q<HTMLInputElement>("#mcp-cwd").value = server?.config.transport === "stdio" ? server.config.cwd ?? "" : "";
    this.q<HTMLInputElement>("#mcp-url").value = server?.config.transport === "streamable_http" ? server.config.url : "";
    this.replaceSecretRows("env", server?.config.transport === "stdio" ? server.config.env : {});
    this.replaceSecretRows("header", server?.config.transport === "streamable_http" ? server.config.headers : {});
    this.q<HTMLDivElement>("#mcp-test-result").hidden = true;
    this.updateTransportFields();
  }

  /**
   * 关闭编辑表单并清理本次测试和授权状态。
   */
  private closeEditor(): void {
    this.q<HTMLFormElement>("#mcp-editor").hidden = true;
    this.editingId = null;
    this.testedFingerprint = null;
    this.authorizedInsecureFingerprint = null;
  }

  /**
   * 根据传输类型切换 stdio 和 HTTP 配置字段。
   */
  private updateTransportFields(): void {
    const isHttp = this.q<HTMLSelectElement>("#mcp-transport").value === "streamable_http";
    this.q<HTMLDivElement>("#mcp-stdio-fields").hidden = isHttp;
    this.q<HTMLDivElement>("#mcp-http-fields").hidden = !isHttp;
  }

  /**
   * 使用配置值重建环境变量或 Header 密钥行。
   *
   * @param kind - 密钥行类型。
   * @param values - 键值形式的配置内容。
   */
  private replaceSecretRows(kind: "env" | "header", values: Record<string, string>): void {
    const rows = kind === "env" ? this.envRows : this.headerRows;
    rows.splice(0).forEach((row) => row.element.remove());
    for (const [key, value] of Object.entries(values)) this.addSecretRow(kind, key, value);
  }

  /**
   * 添加一行支持按住显示的密钥输入控件。
   *
   * @param kind - 环境变量或 HTTP Header。
   * @param initialKey - 初始键名。
   * @param initialValue - 初始密钥值。
   */
  private addSecretRow(kind: "env" | "header", initialKey = "", initialValue = ""): void {
    const element = document.createElement("div");
    element.className = "mcp-secret-row";
    const key = document.createElement("input");
    key.className = "ui-control ui-control--small";
    key.placeholder = kind === "env" ? "VARIABLE" : "Header-Name";
    key.value = initialKey;
    const value = document.createElement("input");
    value.className = "ui-control ui-control--small";
    value.type = "password";
    value.placeholder = "值";
    value.value = initialValue;
    const reveal = this.actionButton("按住显示", () => undefined);
    reveal.addEventListener("pointerdown", () => { value.type = "text"; });
    /** 在按住显示结束后重新遮蔽密钥值。 */
    const hide = (): void => { value.type = "password"; };
    reveal.addEventListener("pointerup", hide);
    reveal.addEventListener("pointerleave", hide);
    reveal.addEventListener("pointercancel", hide);
    reveal.addEventListener("blur", hide);
    const rows = kind === "env" ? this.envRows : this.headerRows;
    const row: SecretRow = { key, value, element };
    const remove = this.actionButton("删除", () => {
      element.remove();
      rows.splice(rows.indexOf(row), 1);
      this.testedFingerprint = null;
    }, "danger");
    element.append(key, value, reveal, remove);
    this.q<HTMLDivElement>(kind === "env" ? "#mcp-env-rows" : "#mcp-header-rows").append(element);
    rows.push(row);
  }

  /**
   * 收集有效密钥输入行并转换为键值对象。
   *
   * @param rows - 待收集的密钥输入行。
   * @returns 已忽略空键名的配置对象。
   */
  private collectRows(rows: SecretRow[]): Record<string, string> {
    return Object.fromEntries(rows.filter((row) => row.key.value.trim()).map((row) => [row.key.value.trim(), row.value.value]));
  }

  /**
   * 读取并执行前端基础校验后构造 Server 配置。
   *
   * @returns 与所选传输类型匹配的 MCP Server 配置。
   * @throws {Error} ID、名称、Endpoint 或 stdio 命令不合法时抛出。
   */
  private readConfig(): MCPServerConfig {
    const common = {
      id: this.q<HTMLInputElement>("#mcp-id").value.trim(),
      name: this.q<HTMLInputElement>("#mcp-name").value.trim(),
      enabled: this.q<HTMLInputElement>("#mcp-enabled").checked,
      connect_timeout_seconds: Number(this.q<HTMLInputElement>("#mcp-connect-timeout").value),
      call_timeout_seconds: Number(this.q<HTMLInputElement>("#mcp-call-timeout").value),
    };
    if (!common.id || !/^[A-Za-z0-9_-]{1,32}$/.test(common.id)) throw new Error("ID 只能包含字母、数字、下划线和连字符");
    if (!common.name) throw new Error("名称不能为空");
    if (this.q<HTMLSelectElement>("#mcp-transport").value === "streamable_http") {
      const url = this.q<HTMLInputElement>("#mcp-url").value.trim();
      if (classifyHttpEndpoint(url).kind === "invalid") throw new Error("Endpoint 必须是有效的 HTTP 或 HTTPS 地址");
      return { ...common, transport: "streamable_http", url, headers: this.collectRows(this.headerRows) };
    }
    const command = this.q<HTMLInputElement>("#mcp-command").value.trim();
    if (!command) throw new Error("stdio 命令不能为空");
    return {
      ...common,
      transport: "stdio",
      command,
      args: this.q<HTMLTextAreaElement>("#mcp-args").value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
      cwd: this.q<HTMLInputElement>("#mcp-cwd").value.trim() || null,
      env: this.collectRows(this.envRows),
    };
  }

  /**
   * 在 HTTP Endpoint 变化时执行不安全连接确认。
   *
   * @param config - 当前准备测试或保存的 Server 配置。
   * @returns 用户是否允许继续使用该 Endpoint。
   */
  private async authorizeHttp(config: MCPServerConfig): Promise<boolean> {
    if (config.transport !== "streamable_http") return true;
    const fingerprint = fingerprintMcpConfig(config);
    if (this.authorizedInsecureFingerprint === fingerprint) return true;
    const previous = this.servers.find((server) => server.config.id === this.editingId)?.config;
    const approved = await authorizeBaseUrlChange({
      previousUrl: previous?.transport === "streamable_http" ? previous.url : "",
      nextUrl: config.url,
      confirmInsecure: (url) => this.confirmDialog.open({
        title: "未加密 MCP 连接警告",
        message: `MCP Headers 可能通过未加密 HTTP 发送到 ${url}。`,
        confirmText: "仍然继续",
        cancelText: "取消",
        variant: "warning",
      }),
    });
    if (approved && classifyHttpEndpoint(config.url).kind === "insecure_http") {
      this.authorizedInsecureFingerprint = fingerprint;
    }
    return approved;
  }

  /**
   * 测试编辑表单中的 MCP Server 配置并记录测试指纹。
   */
  private async testCurrent(): Promise<void> {
    try {
      const config = this.readConfig();
      if (!await this.authorizeHttp(config)) return;
      const result = await window.desktopPetApi.testMcpServer(config);
      this.testedFingerprint = fingerprintMcpConfig(config);
      const element = this.q<HTMLDivElement>("#mcp-test-result");
      element.hidden = false;
      element.textContent = `连接成功，发现 ${result.tools.length} 个工具：${result.tools.map((tool) => tool.name).join("、") || "无"}`;
      this.toast.success("MCP 连接测试成功");
    } catch (error) {
      this.toast.error(appendErrorMessage("MCP 连接测试失败", error));
    }
  }

  /**
   * 校验测试状态后创建或更新 MCP Server。
   */
  private async saveCurrent(): Promise<void> {
    try {
      const config = this.readConfig();
      if (config.enabled && this.testedFingerprint !== fingerprintMcpConfig(config)) {
        throw new Error("启用的服务必须在最后一次修改连接参数后通过测试");
      }
      if (!await this.authorizeHttp(config)) return;
      if (this.editingId) await window.desktopPetApi.updateMcpServer(this.editingId, config);
      else await window.desktopPetApi.createMcpServer(config);
      this.toast.success("MCP 服务已保存");
      this.closeEditor();
      await this.callback?.({ type: "settings-invalidated", page: "mcp" });
    } catch (error) {
      this.toast.error(appendErrorMessage("保存 MCP 服务失败", error));
    }
  }

  /**
   * 测试一个已保存的 MCP Server 配置。
   *
   * @param server - 待测试的已保存 Server。
   */
  private async testSaved(server: MCPServerView): Promise<void> {
    try {
      const result = await window.desktopPetApi.testMcpServer(server.config);
      this.toast.success(`连接成功，发现 ${result.tools.length} 个工具`);
    } catch (error) {
      this.toast.error(appendErrorMessage("测试 MCP 服务失败", error));
    }
  }

  /**
   * 请求后端重连指定 MCP Server 并刷新页面。
   *
   * @param serverId - 待重连的 MCP Server ID。
   */
  private async reconnect(serverId: string): Promise<void> {
    try {
      await window.desktopPetApi.reconnectMcpServer(serverId);
      await this.callback?.({ type: "settings-invalidated", page: "mcp" });
      this.toast.success("MCP 服务已重连");
    } catch (error) {
      this.toast.error(appendErrorMessage("重连 MCP 服务失败", error));
    }
  }

  /**
   * 经用户确认后删除 MCP Server 及模型引用。
   *
   * @param serverId - 待删除的 MCP Server ID。
   * @param name - 用于确认对话框展示的 Server 名称。
   */
  private async remove(serverId: string, name: string): Promise<void> {
    const server = this.servers.find((item) => item.config.id === serverId);
    const policyCount = server?.affected_model_count ?? 0;
    const confirmed = await this.confirmDialog.open({
      title: "删除 MCP 服务",
      message: `将删除 ${name} 并清理所有模型引用。受影响模型：${policyCount} 个。`,
      confirmText: "确认删除",
      cancelText: "取消",
      variant: "danger",
    });
    if (!confirmed) return;
    try {
      const result = await window.desktopPetApi.deleteMcpServer(serverId);
      delete this.policies.servers[serverId];
      await this.callback?.({ type: "settings-invalidated", page: "mcp" });
      this.toast.success(`已删除，清理 ${result.affected_sessions.length} 个模型引用`);
    } catch (error) {
      this.toast.error(appendErrorMessage("删除 MCP 服务失败", error));
    }
  }

  /**
   * 重新读取全部 MCP Server 和工具目录并刷新卡片。
   */
  private async refresh(): Promise<void> {
    this.servers = await window.desktopPetApi.getMcpServers();
    const entries = await Promise.all(this.servers.map(async (server) => {
      try { return [server.config.id, await window.desktopPetApi.getMcpServerTools(server.config.id)] as const; }
      catch { return [server.config.id, [] as MCPToolInfo[]] as const; }
    }));
    this.tools = new Map(entries);
    this.renderServers();
  }
}
