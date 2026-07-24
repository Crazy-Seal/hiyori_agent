import "./logs.css";

import type {
  LogLevel,
  LogRecord,
  LogSide,
  LogSource,
} from "../../shared-types.js";
import { LogViewerModel } from "./log-viewer-model.js";

const getElement = <T extends HTMLElement>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`日志窗口缺少元素: ${selector}`);
  return element;
};

interface SideElements {
  list: HTMLDivElement;
  count: HTMLDivElement;
  level: HTMLSelectElement;
  source: HTMLSelectElement;
  autoscroll: HTMLInputElement;
  clear: HTMLButtonElement;
}

const elements: Record<LogSide, SideElements> = {
  frontend: {
    list: getElement("#frontend-logs"),
    count: getElement("#frontend-count"),
    level: getElement("#frontend-level"),
    source: getElement("#frontend-source"),
    autoscroll: getElement("#frontend-autoscroll"),
    clear: getElement("#frontend-clear"),
  },
  backend: {
    list: getElement("#backend-logs"),
    count: getElement("#backend-count"),
    level: getElement("#backend-level"),
    source: getElement("#backend-source"),
    autoscroll: getElement("#backend-autoscroll"),
    clear: getElement("#backend-clear"),
  },
};

const search = getElement<HTMLInputElement>("#log-search");
const pauseButton = getElement<HTMLButtonElement>("#log-pause-btn");
const status = getElement<HTMLDivElement>("#log-status");
let model: LogViewerModel | null = null;
const MAX_RENDERED_ROWS = 1_000;

const selectedSourceSet = (value: string): Set<LogSource> =>
  value ? new Set([value as LogSource]) : new Set<LogSource>();

const renderSide = (side: LogSide): void => {
  if (!model) return;
  const sideElements = elements[side];
  const records = model.filter(side, {
    query: search.value,
    minimumLevel: sideElements.level.value as LogLevel,
    sources: selectedSourceSet(sideElements.source.value),
  });
  const visibleRecords = records.slice(-MAX_RENDERED_ROWS);
  const fragment = document.createDocumentFragment();
  if (visibleRecords.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state ui-empty-state";
    empty.textContent = "当前筛选条件下没有日志";
    fragment.append(empty);
  } else {
    for (const record of visibleRecords) fragment.append(createLogRow(record));
  }
  sideElements.list.replaceChildren(fragment);
  sideElements.count.textContent = records.length > visibleRecords.length
    ? `${visibleRecords.length}/${records.length} 条`
    : `${records.length} 条`;
  if (sideElements.autoscroll.checked) {
    sideElements.list.scrollTop = sideElements.list.scrollHeight;
  }
};

const createLogRow = (record: LogRecord): HTMLDivElement => {
  const row = document.createElement("div");
  row.className = "log-row";
  row.dataset.level = record.level;

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = new Date(record.timestamp).toLocaleTimeString("zh-CN", { hour12: false });
  const level = document.createElement("span");
  level.className = "log-level";
  level.textContent = record.level.toUpperCase();
  const source = document.createElement("span");
  source.className = "log-source";
  source.textContent = `[${record.source}/${record.scope}]`;
  const message = document.createElement("span");
  message.className = "log-message";
  message.textContent = record.message;
  row.append(time, level, source, message);
  return row;
};

const renderAll = (): void => {
  renderSide("frontend");
  renderSide("backend");
};

const setupControls = (): void => {
  search.addEventListener("input", renderAll);
  pauseButton.addEventListener("click", () => {
    if (!model) return;
    const paused = !model.isPaused();
    model.setPaused(paused);
    pauseButton.textContent = paused ? "继续刷新" : "暂停刷新";
    pauseButton.setAttribute("aria-pressed", String(paused));
    status.textContent = paused ? "界面已暂停，日志仍在持续写入文件" : "实时日志流已连接";
    if (!paused) renderAll();
  });
  getElement("#open-log-directory-btn").addEventListener("click", () => {
    void window.desktopPetApi.openLogDirectory().catch((error: unknown) => {
      status.textContent = error instanceof Error ? error.message : "无法打开日志目录";
    });
  });
  getElement("#log-min-btn").addEventListener("click", () => {
    window.desktopPetApi.minimizeCurrentWindow();
  });
  getElement("#log-close-btn").addEventListener("click", () => {
    window.desktopPetApi.closeCurrentWindow();
  });

  for (const side of ["frontend", "backend"] as const) {
    const sideElements = elements[side];
    sideElements.level.addEventListener("change", () => renderSide(side));
    sideElements.source.addEventListener("change", () => renderSide(side));
    sideElements.autoscroll.addEventListener("change", () => {
      if (sideElements.autoscroll.checked) renderSide(side);
    });
    sideElements.list.addEventListener("scroll", () => {
      const distance = sideElements.list.scrollHeight
        - sideElements.list.scrollTop
        - sideElements.list.clientHeight;
      if (distance > 24 && sideElements.autoscroll.checked) {
        sideElements.autoscroll.checked = false;
      }
    });
    sideElements.clear.addEventListener("click", () => {
      void window.desktopPetApi.clearLogBuffer(side).then(() => {
        model?.clear(side);
        renderSide(side);
      }).catch((error: unknown) => {
        status.textContent = error instanceof Error ? error.message : "清空日志视图失败";
      });
    });
  }
};

const start = async (): Promise<void> => {
  const earlyRecords: LogRecord[] = [];
  let acceptingEarly = true;
  const unsubscribe = window.desktopPetApi.onLogBatch((batch) => {
    if (acceptingEarly) {
      earlyRecords.push(...batch.records);
      return;
    }
    model?.append(batch.records);
    if (!model?.isPaused()) renderAll();
  });
  window.addEventListener("beforeunload", unsubscribe, { once: true });

  const snapshot = await window.desktopPetApi.getLogSnapshot();
  model = new LogViewerModel(snapshot);
  model.append(earlyRecords);
  acceptingEarly = false;
  setupControls();
  renderAll();
  status.textContent = "实时日志流已连接";
};

void start().catch((error: unknown) => {
  status.textContent = error instanceof Error ? error.message : "日志控制台初始化失败";
});
