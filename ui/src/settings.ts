import "./settings.css";

const sidebar = document.querySelector<HTMLDivElement>("#settings-sidebar");
const minBtn = document.querySelector<HTMLButtonElement>("#settings-min-btn");
const closeBtn = document.querySelector<HTMLButtonElement>("#settings-close-btn");
const importModelBtn = document.querySelector<HTMLButtonElement>("#import-model-btn");
const modelList = document.querySelector<HTMLDivElement>("#model-list");
const importPreview = document.querySelector<HTMLDivElement>("#import-preview");
const previewName = document.querySelector<HTMLDivElement>("#preview-name");
const previewType = document.querySelector<HTMLDivElement>("#preview-type");
const previewEntry = document.querySelector<HTMLDivElement>("#preview-entry");
const confirmImportBtn = document.querySelector<HTMLButtonElement>("#confirm-import-btn");
const cancelImportBtn = document.querySelector<HTMLButtonElement>("#cancel-import-btn");
const offsetXSlider = document.querySelector<HTMLInputElement>("#slider-offset-x");
const offsetYSlider = document.querySelector<HTMLInputElement>("#slider-offset-y");
const offsetXValue = document.querySelector<HTMLSpanElement>("#slider-offset-x-value");
const offsetYValue = document.querySelector<HTMLSpanElement>("#slider-offset-y-value");
const followCursorCheckbox = document.querySelector<HTMLInputElement>("#checkbox-follow-cursor");
const toolsTableBody = document.querySelector<HTMLTableSectionElement>("#tools-table-body");
const toolsEmpty = document.querySelector<HTMLDivElement>("#tools-empty");
const llmBaseUrlInput = document.querySelector<HTMLInputElement>("#llm-base-url");
const llmApiKeyInput = document.querySelector<HTMLInputElement>("#llm-api-key");
const llmModelNameInput = document.querySelector<HTMLInputElement>("#llm-model-name");
const llmTemperatureInput = document.querySelector<HTMLInputElement>("#llm-temperature");
const llmSystemPromptInput = document.querySelector<HTMLTextAreaElement>("#llm-system-prompt");
const llmConfirmBtn = document.querySelector<HTMLButtonElement>("#llm-confirm-btn");
const toolsConfirmBtn = document.querySelector<HTMLButtonElement>("#tools-confirm-btn");
const deleteConfirmDialog = document.querySelector<HTMLDivElement>("#delete-confirm-dialog");
const deleteConfirmCancelBtn = document.querySelector<HTMLButtonElement>("#delete-confirm-cancel");
const deleteConfirmOkBtn = document.querySelector<HTMLButtonElement>("#delete-confirm-ok");

if (
  !sidebar ||
  !minBtn ||
  !closeBtn ||
  !importModelBtn ||
  !modelList ||
  !importPreview ||
  !previewName ||
  !previewType ||
  !previewEntry ||
  !confirmImportBtn ||
  !cancelImportBtn ||
  !offsetXSlider ||
  !offsetYSlider ||
  !offsetXValue ||
  !offsetYValue ||
  !followCursorCheckbox ||
  !toolsTableBody ||
  !toolsEmpty ||
  !llmBaseUrlInput ||
  !llmApiKeyInput ||
  !llmModelNameInput ||
  !llmTemperatureInput ||
  !llmSystemPromptInput ||
  !llmConfirmBtn ||
  !toolsConfirmBtn ||
  !deleteConfirmDialog ||
  !deleteConfirmCancelBtn ||
  !deleteConfirmOkBtn
) {
  throw new Error("设置窗口初始化失败");
}

type ModelConfig = {
  activeModelId: string;
  models: Array<{
    id: string;
    name: string;
    sessionId: string;
    source: "builtin" | "custom";
    deletable: boolean;
    offsetX: number;
    offsetY: number;
    userScale: number;
    followCursor: boolean;
  }>;
};

let currentConfig: ModelConfig | null = null;
let pendingImport: { selectedPath: string; suggestedName: string; sourceType: "directory"; entryRelativePath: string } | null = null;
let syncingSliders = false;
let currentPage = "model";
let pendingDeleteConfirm: ((confirmed: boolean) => void) | null = null;

type ChatSettingsState = {
  session_id: string;
  model_name: string;
  openai_api_key: string;
  openai_base_url: string;
  temperature: number;
  system_prompt: string;
  tools_list: string[];
};

let chatSettingsState: ChatSettingsState | null = null;
let availableTools: Array<{ name: string }> = [];

const closeDeleteConfirmDialog = (confirmed: boolean) => {
  deleteConfirmDialog.hidden = true;
  deleteConfirmDialog.setAttribute("aria-hidden", "true");

  const resolver = pendingDeleteConfirm;
  pendingDeleteConfirm = null;
  if (resolver) {
    resolver(confirmed);
  }
};

const openDeleteConfirmDialog = (): Promise<boolean> => {
  deleteConfirmDialog.hidden = false;
  deleteConfirmDialog.setAttribute("aria-hidden", "false");
  return new Promise<boolean>((resolve) => {
    pendingDeleteConfirm = resolve;
  });
};

const renderToolsTable = (tools: Array<{ name: string }>) => {
  toolsTableBody.innerHTML = "";

  if (tools.length === 0) {
    toolsEmpty.hidden = false;
    return;
  }

  toolsEmpty.hidden = true;
  for (const tool of tools) {
    const row = document.createElement("tr");

    const checkCell = document.createElement("td");
    checkCell.className = "col-check";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.toolName = tool.name;
    checkbox.checked = Boolean(chatSettingsState?.tools_list.includes(tool.name));
    checkCell.appendChild(checkbox);

    const nameCell = document.createElement("td");
    nameCell.textContent = tool.name;

    row.appendChild(checkCell);
    row.appendChild(nameCell);
    toolsTableBody.appendChild(row);
  }
};

const collectSelectedTools = (): string[] => {
  const selected: string[] = [];
  toolsTableBody.querySelectorAll<HTMLInputElement>('input[type="checkbox"][data-tool-name]').forEach((input) => {
    if (input.checked && input.dataset.toolName) {
      selected.push(input.dataset.toolName);
    }
  });
  return selected;
};

const renderLlmSettings = () => {
  if (!chatSettingsState) {
    return;
  }

  llmBaseUrlInput.value = chatSettingsState.openai_base_url;
  llmApiKeyInput.value = chatSettingsState.openai_api_key;
  llmModelNameInput.value = chatSettingsState.model_name;
  llmTemperatureInput.value = String(chatSettingsState.temperature);
  llmSystemPromptInput.value = chatSettingsState.system_prompt;
};

const renderToolsSelection = () => {
  renderToolsTable(availableTools);
};

const refreshTools = async () => {
  const result = await window.desktopPetApi.getAvailableTools();
  availableTools = result.tools;
  renderToolsSelection();
};

const initChatSettings = async () => {
  chatSettingsState = await window.desktopPetApi.getChatSettings();
  renderLlmSettings();
  renderToolsSelection();
};

const applyPageEnterRender = (page: string) => {
  if (page === "llm") {
    renderLlmSettings();
    return;
  }

  if (page === "tools") {
    renderToolsSelection();
  }
};

const clearImportPreview = () => {
  pendingImport = null;
  previewName.textContent = "";
  previewType.textContent = "";
  previewEntry.textContent = "";
  importPreview.hidden = true;
};

const renderModelList = (config: ModelConfig) => {
  modelList.innerHTML = "";

  for (const model of config.models) {
    const row = document.createElement("div");
    row.className = "model-item-row";

    const button = document.createElement("button");
    button.type = "button";
    button.className = `model-item ${model.id === config.activeModelId ? "active" : ""}`;
    button.dataset.modelId = model.id;
    button.innerHTML = `<div class="model-name">${model.name}</div><div class="model-session">session_id: ${model.sessionId}</div>`;

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "delete-model-btn";
    deleteButton.dataset.modelId = model.id;
    deleteButton.textContent = "删除";
    deleteButton.disabled = !model.deletable;

    row.appendChild(button);
    row.appendChild(deleteButton);
    modelList.appendChild(row);
  }
};

const renderTransformSliders = (config: ModelConfig) => {
  const active = config.models.find((item) => item.id === config.activeModelId);
  const offsetX = active?.offsetX ?? 0;
  const offsetY = active?.offsetY ?? 0;
  const followCursor = active?.followCursor ?? true;

  syncingSliders = true;
  offsetXSlider.value = String(Math.round(offsetX));
  offsetYSlider.value = String(Math.round(offsetY));
  offsetXValue.textContent = `${Math.round(offsetX)}`;
  offsetYValue.textContent = `${Math.round(offsetY)}`;
  followCursorCheckbox.checked = followCursor;
  syncingSliders = false;
};

const refreshModelConfig = async () => {
  const config = await window.desktopPetApi.getModelConfig();
  currentConfig = config;
  renderModelList(config);
  renderTransformSliders(config);
};

const refreshAfterModelChanged = async () => {
  await Promise.all([refreshModelConfig(), initChatSettings()]);
  applyPageEnterRender(currentPage);
};

const updateActiveModelTransform = async () => {
  if (!currentConfig || syncingSliders) {
    return;
  }

  const modelId = currentConfig.activeModelId;
  const offsetX = Number(offsetXSlider.value);
  const offsetY = Number(offsetYSlider.value);
  offsetXValue.textContent = `${offsetX}`;
  offsetYValue.textContent = `${offsetY}`;

  await window.desktopPetApi.updateModelTransform({
    modelId,
    offsetX,
    offsetY,
    followCursor: followCursorCheckbox.checked
  });

  const target = currentConfig.models.find((item) => item.id === modelId);
  if (target) {
    target.offsetX = offsetX;
    target.offsetY = offsetY;
    target.followCursor = followCursorCheckbox.checked;
  }
};

sidebar.addEventListener("click", (event) => {
  const target = event.target as HTMLElement | null;
  const tab = target?.closest<HTMLButtonElement>(".settings-tab");
  if (!tab) {
    return;
  }

  const page = tab.dataset.page;
  if (!page) {
    return;
  }

  currentPage = page;

  document.querySelectorAll<HTMLButtonElement>(".settings-tab").forEach((item) => {
    item.classList.toggle("active", item === tab);
  });

  document.querySelectorAll<HTMLDivElement>(".settings-page").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });

  applyPageEnterRender(page);
});

minBtn.addEventListener("click", () => {
  window.desktopPetApi.minimizeCurrentWindow();
});

closeBtn.addEventListener("click", () => {
  window.desktopPetApi.closeCurrentWindow();
});

modelList.addEventListener("click", async (event) => {
  const target = event.target as HTMLElement | null;
  const deleteBtn = target?.closest<HTMLButtonElement>(".delete-model-btn");
  if (deleteBtn) {
    const modelId = deleteBtn.dataset.modelId;
    if (!modelId || deleteBtn.disabled) {
      return;
    }

    const confirmed = await openDeleteConfirmDialog();
    if (!confirmed) {
      return;
    }

    await window.desktopPetApi.deleteModel(modelId);
    await refreshAfterModelChanged();
    return;
  }

  const item = target?.closest<HTMLButtonElement>(".model-item");
  if (!item) {
    return;
  }

  const modelId = item.dataset.modelId;
  if (!modelId || currentConfig?.activeModelId === modelId) {
    return;
  }

  await window.desktopPetApi.setActiveModel(modelId);
  await refreshAfterModelChanged();
});

importModelBtn.addEventListener("click", async () => {
  const preview = await window.desktopPetApi.previewLive2DImport();
  if (!preview) {
    return;
  }

  pendingImport = preview;
  previewName.textContent = `模型名：${preview.suggestedName}`;
  previewType.textContent = "来源类型：文件夹";
  previewEntry.textContent = `识别入口：${preview.entryRelativePath}`;
  importPreview.hidden = false;
});

confirmImportBtn.addEventListener("click", async () => {
  if (!pendingImport) {
    return;
  }

  await window.desktopPetApi.importLive2DModel({
    selectedPath: pendingImport.selectedPath,
    suggestedName: pendingImport.suggestedName
  });
  clearImportPreview();
  await refreshAfterModelChanged();
});

cancelImportBtn.addEventListener("click", () => {
  clearImportPreview();
});

offsetXSlider.addEventListener("input", () => {
  void updateActiveModelTransform();
});

offsetYSlider.addEventListener("input", () => {
  void updateActiveModelTransform();
});

followCursorCheckbox.addEventListener("change", () => {
  void updateActiveModelTransform();
});

llmConfirmBtn.addEventListener("click", async () => {
  if (!chatSettingsState) {
    return;
  }

  chatSettingsState = {
    ...chatSettingsState,
    openai_base_url: llmBaseUrlInput.value.trim(),
    openai_api_key: llmApiKeyInput.value.trim(),
    model_name: llmModelNameInput.value.trim(),
    temperature: Number.isFinite(Number(llmTemperatureInput.value))
      ? Number(llmTemperatureInput.value)
      : chatSettingsState.temperature,
    system_prompt: llmSystemPromptInput.value
  };

  await window.desktopPetApi.updateChatSettings(chatSettingsState);
});

toolsConfirmBtn.addEventListener("click", async () => {
  if (!chatSettingsState) {
    return;
  }

  chatSettingsState = {
    ...chatSettingsState,
    tools_list: collectSelectedTools()
  };

  await window.desktopPetApi.updateChatSettings(chatSettingsState);
});

deleteConfirmCancelBtn.addEventListener("click", () => {
  closeDeleteConfirmDialog(false);
});

deleteConfirmOkBtn.addEventListener("click", () => {
  closeDeleteConfirmDialog(true);
});

deleteConfirmDialog.addEventListener("click", (event) => {
  if (event.target === deleteConfirmDialog) {
    closeDeleteConfirmDialog(false);
  }
});

const unsubscribeTransformChanged = window.desktopPetApi.onModelTransformChanged((payload) => {
  if (!currentConfig || payload.id !== currentConfig.activeModelId) {
    return;
  }

  const target = currentConfig.models.find((item) => item.id === payload.id);
  if (!target) {
    return;
  }

  target.offsetX = payload.offsetX;
  target.offsetY = payload.offsetY;
  target.userScale = payload.userScale;
  target.followCursor = payload.followCursor;
  renderTransformSliders(currentConfig);
});

const unsubscribeModelChanged = window.desktopPetApi.onModelChanged(() => {
  void Promise.all([refreshModelConfig(), initChatSettings()]).then(() => {
    applyPageEnterRender(currentPage);
  });
});

window.addEventListener("beforeunload", () => {
  unsubscribeTransformChanged();
  unsubscribeModelChanged();
});

void Promise.all([refreshTools(), refreshModelConfig(), initChatSettings()]).then(() => {
  applyPageEnterRender(currentPage);
});
