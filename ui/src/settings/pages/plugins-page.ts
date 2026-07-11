import type {
  ChatSettingsState,
  ISettingsPage,
  PageEditingData,
  PageEventCallback,
  PageRenderData,
  PluginItem,
} from "../types.js";

type PluginSettingsMap = NonNullable<ChatSettingsState["agent_plugins"]>;

const CONFIG_LABELS: Record<string, string> = {
  enable_diary: "启用日记",
  enable_episodic: "启用情景记忆",
  enable_semantic: "启用语义记忆",
  summary_every_human_messages: "每多少轮总结长期记忆",
};

const NUMBER_FIELDS = new Set([
  "summary_every_human_messages",
]);

const BOOLEAN_FIELDS = new Set([
  "enable_diary",
  "enable_episodic",
  "enable_semantic",
]);

type JsonSchemaProperty = {
  minimum?: unknown;
};

type JsonSchemaWithProperties = {
  properties?: Record<string, JsonSchemaProperty>;
};

const hasSchemaProperties = (schema: unknown): schema is JsonSchemaWithProperties => (
  typeof schema === "object" && schema !== null && "properties" in schema
);

export const getNumberFieldMinimum = (plugin: PluginItem, key: string): number => {
  if (!hasSchemaProperties(plugin.config_schema)) {
    return 0;
  }

  const minimum = plugin.config_schema.properties?.[key]?.minimum;
  return typeof minimum === "number" ? minimum : 0;
};

export class PluginsPage implements ISettingsPage {
  private container: HTMLDivElement;
  private empty: HTMLDivElement;
  private confirmBtn: HTMLButtonElement;
  private eventCallback?: PageEventCallback;

  constructor(
    container: HTMLDivElement,
    empty: HTMLDivElement,
    confirmBtn: HTMLButtonElement
  ) {
    this.container = container;
    this.empty = empty;
    this.confirmBtn = confirmBtn;
    this.confirmBtn.addEventListener("click", () => {
      this.eventCallback?.({ type: "submit", page: "memory" });
    });
  }

  onEvent(callback: PageEventCallback): void {
    this.eventCallback = callback;
  }

  render(data: PageRenderData): void {
    const availablePlugins = data.dependencies?.availablePlugins || [];
    const savedPlugins = data.saved.agent_plugins || {};
    this.container.innerHTML = "";

    if (availablePlugins.length === 0) {
      this.empty.hidden = false;
      return;
    }

    this.empty.hidden = true;
    for (const plugin of availablePlugins) {
      this.container.appendChild(this.renderPluginCard(plugin, savedPlugins));
    }
  }

  getEditingData(): PageEditingData {
    const agent_plugins: PluginSettingsMap = {};
    this.container.querySelectorAll<HTMLElement>("[data-plugin-name]").forEach((card) => {
      const pluginName = card.dataset.pluginName;
      if (!pluginName) return;

      const enabledInput = card.querySelector<HTMLInputElement>('input[data-plugin-enabled="true"]');
      const inherent = card.dataset.pluginInherent === "true";
      const config: Record<string, unknown> = {};

      card.querySelectorAll<HTMLInputElement>("input[data-config-key]").forEach((input) => {
        const key = input.dataset.configKey;
        if (!key) return;
        config[key] = input.type === "checkbox" ? input.checked : Number(input.value);
      });

      agent_plugins[pluginName] = {
        enabled: inherent || Boolean(enabledInput?.checked),
        config,
      };
    });

    return { plugins: { agent_plugins } };
  }

  private renderPluginCard(plugin: PluginItem, savedPlugins: PluginSettingsMap): HTMLElement {
    const saved = savedPlugins[plugin.name];
    const config = {
      ...plugin.default_config,
      ...(saved?.config || {}),
    };
    const enabled = plugin.inherent || saved?.enabled === true;

    const card = document.createElement("div");
    card.className = "plugin-card";
    card.dataset.pluginName = plugin.name;
    card.dataset.pluginInherent = String(plugin.inherent);

    const header = document.createElement("div");
    header.className = "plugin-card-header";

    const titleWrap = document.createElement("div");
    const title = document.createElement("div");
    title.className = "plugin-card-title";
    title.textContent = plugin.name;
    const desc = document.createElement("div");
    desc.className = "plugin-card-desc";
    desc.textContent = plugin.description || "暂无说明";
    titleWrap.append(title, desc);

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "plugin-toggle";
    const toggleText = document.createElement("span");
    toggleText.textContent = plugin.inherent ? "固有插件" : "启用";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.dataset.pluginEnabled = "true";
    toggle.checked = enabled;
    toggle.disabled = plugin.inherent;
    toggleLabel.append(toggleText, toggle);

    header.append(titleWrap, toggleLabel);
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "plugin-config-grid";
    for (const [key, value] of Object.entries(config)) {
      if (!NUMBER_FIELDS.has(key) && !BOOLEAN_FIELDS.has(key)) continue;
      body.appendChild(this.renderConfigField(plugin, key, value));
    }
    card.appendChild(body);

    return card;
  }

  private renderConfigField(plugin: PluginItem, key: string, value: unknown): HTMLElement {
    const label = document.createElement("label");
    label.className = "plugin-config-field";

    const text = document.createElement("span");
    text.textContent = CONFIG_LABELS[key] || key;

    const input = document.createElement("input");
    input.dataset.configKey = key;
    if (BOOLEAN_FIELDS.has(key)) {
      input.type = "checkbox";
      input.checked = Boolean(value);
    } else {
      input.type = "number";
      input.min = String(getNumberFieldMinimum(plugin, key));
      input.step = "1";
      input.value = String(typeof value === "number" ? value : 0);
    }

    label.append(text, input);
    return label;
  }
}
