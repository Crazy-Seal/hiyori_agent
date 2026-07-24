import "./logs.css";

import type {
  LogLevel,
  LogRecord,
  LogSide,
  LogSource,
} from "../../shared-types.js";
import {
  LogViewerModel,
  type LogFilter,
} from "./log-viewer-model.js";
import {
  LogViewportState,
  resolveAnchoredScrollTop,
  selectRestorationAnchorId,
} from "./log-viewport.js";

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

interface SideViewState {
  viewport: LogViewportState;
  renderedIds: Set<number>;
  matchingCount: number;
  bottomFrame: number | null;
  userIntentTimer: number | null;
}

interface ViewAnchor {
  recordId: number;
  offset: number;
  scrollTop: number;
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

const viewStates: Record<LogSide, SideViewState> = {
  frontend: {
    viewport: new LogViewportState(elements.frontend.autoscroll.checked),
    renderedIds: new Set(),
    matchingCount: 0,
    bottomFrame: null,
    userIntentTimer: null,
  },
  backend: {
    viewport: new LogViewportState(elements.backend.autoscroll.checked),
    renderedIds: new Set(),
    matchingCount: 0,
    bottomFrame: null,
    userIntentTimer: null,
  },
};

const search = getElement<HTMLInputElement>("#log-search");
const pauseButton = getElement<HTMLButtonElement>("#log-pause-btn");
const status = getElement<HTMLDivElement>("#log-status");
const resizeObservers: ResizeObserver[] = [];
let model: LogViewerModel | null = null;
const MAX_RENDERED_ROWS = 1_000;
const USER_SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
]);

const selectedSourceSet = (value: string): Set<LogSource> =>
  value ? new Set([value as LogSource]) : new Set<LogSource>();

const getFilter = (side: LogSide): LogFilter => ({
  query: search.value,
  minimumLevel: elements[side].level.value as LogLevel,
  sources: selectedSourceSet(elements[side].source.value),
});

const createBottomAnchor = (): HTMLDivElement => {
  const anchor = document.createElement("div");
  anchor.className = "log-bottom-anchor";
  anchor.setAttribute("aria-hidden", "true");
  return anchor;
};

const getBottomAnchor = (side: LogSide): HTMLDivElement => {
  const list = elements[side].list;
  const existing = list.querySelector<HTMLDivElement>(".log-bottom-anchor");
  if (existing) return existing;
  const anchor = createBottomAnchor();
  list.append(anchor);
  return anchor;
};

const scrollToBottom = (side: LogSide): void => {
  const sideElements = elements[side];
  const state = viewStates[side];
  if (!state.viewport.isFollowing()) return;

  const applyBottom = (): void => {
    if (!state.viewport.isFollowing()) return;
    getBottomAnchor(side);
    sideElements.list.scrollTop = sideElements.list.scrollHeight;
  };

  applyBottom();
  if (state.bottomFrame !== null) cancelAnimationFrame(state.bottomFrame);
  state.bottomFrame = requestAnimationFrame(() => {
    state.bottomFrame = null;
    applyBottom();
  });
};

const captureViewAnchor = (side: LogSide): ViewAnchor | null => {
  const list = elements[side].list;
  const listTop = list.getBoundingClientRect().top;
  const rows = list.querySelectorAll<HTMLElement>(".log-row[data-record-id]");
  for (const row of rows) {
    const rowRect = row.getBoundingClientRect();
    if (rowRect.bottom > listTop) {
      const recordId = Number(row.dataset.recordId);
      if (Number.isFinite(recordId)) {
        return {
          recordId,
          offset: rowRect.top - listTop,
          scrollTop: list.scrollTop,
        };
      }
    }
  }
  return null;
};

const restoreViewAnchor = (
  side: LogSide,
  visibleRecords: readonly LogRecord[],
  previousAnchor: ViewAnchor | null,
): void => {
  if (!previousAnchor) return;
  const list = elements[side].list;
  const targetId = selectRestorationAnchorId(
    visibleRecords.map((record) => record.id),
    previousAnchor.recordId,
  );
  if (targetId === undefined) {
    list.scrollTop = previousAnchor.scrollTop;
    return;
  }
  const target = list.querySelector<HTMLElement>(`[data-record-id="${targetId}"]`);
  if (!target) {
    list.scrollTop = previousAnchor.scrollTop;
    return;
  }
  const currentOffset = target.getBoundingClientRect().top
    - list.getBoundingClientRect().top;
  list.scrollTop = resolveAnchoredScrollTop(
    list.scrollTop,
    currentOffset,
    previousAnchor.offset,
  );
};

const createLogRow = (record: LogRecord): HTMLDivElement => {
  const row = document.createElement("div");
  row.className = "log-row";
  row.dataset.level = record.level;
  row.dataset.recordId = String(record.id);

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

const updateCount = (side: LogSide, matchingCount: number): void => {
  elements[side].count.textContent = matchingCount > MAX_RENDERED_ROWS
    ? `${MAX_RENDERED_ROWS}/${matchingCount} 条`
    : `${matchingCount} 条`;
};

const syncEmptyState = (side: LogSide, matchingCount: number): void => {
  const list = elements[side].list;
  const existing = list.querySelector<HTMLElement>(".empty-state");
  if (matchingCount > 0) {
    existing?.remove();
    return;
  }
  if (existing) return;
  const empty = document.createElement("div");
  empty.className = "empty-state ui-empty-state";
  empty.textContent = "当前筛选条件下没有日志";
  list.insertBefore(empty, getBottomAnchor(side));
};

const rebuildSide = (side: LogSide): void => {
  if (!model) return;
  const state = viewStates[side];
  const previousAnchor = state.viewport.isFollowing() ? null : captureViewAnchor(side);
  const records = model.filter(side, getFilter(side));
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
  fragment.append(createBottomAnchor());

  elements[side].list.replaceChildren(fragment);
  state.renderedIds = new Set(visibleRecords.map((record) => record.id));
  state.matchingCount = records.length;
  updateCount(side, state.matchingCount);

  if (state.viewport.isFollowing()) {
    scrollToBottom(side);
  } else {
    restoreViewAnchor(side, visibleRecords, previousAnchor);
  }
};

const rebuildAll = (): void => {
  rebuildSide("frontend");
  rebuildSide("backend");
};

const removeRenderedRecord = (side: LogSide, recordId: number): void => {
  const state = viewStates[side];
  if (!state.renderedIds.delete(recordId)) return;
  elements[side].list
    .querySelector<HTMLElement>(`[data-record-id="${recordId}"]`)
    ?.remove();
};

const trimRenderedRows = (side: LogSide): void => {
  const list = elements[side].list;
  const state = viewStates[side];
  while (state.renderedIds.size > MAX_RENDERED_ROWS) {
    const first = list.querySelector<HTMLElement>(".log-row[data-record-id]");
    if (!first) break;
    const recordId = Number(first.dataset.recordId);
    first.remove();
    if (Number.isFinite(recordId)) state.renderedIds.delete(recordId);
  }
};

const appendIncomingRecords = (records: readonly LogRecord[]): void => {
  if (!model || records.length === 0) return;
  const delta = model.append(records);
  if (delta.added.length === 0 && delta.removed.length === 0) return;

  const touchedSides = new Set<LogSide>();
  for (const record of delta.removed) {
    if (model.matches(record, getFilter(record.side))) {
      const state = viewStates[record.side];
      state.matchingCount = Math.max(0, state.matchingCount - 1);
      touchedSides.add(record.side);
    }
    removeRenderedRecord(record.side, record.id);
  }
  for (const record of delta.added) {
    const side = record.side;
    if (!model.matches(record, getFilter(side))) continue;
    const state = viewStates[side];
    if (state.renderedIds.has(record.id)) continue;
    state.matchingCount += 1;
    elements[side].list.insertBefore(createLogRow(record), getBottomAnchor(side));
    state.renderedIds.add(record.id);
    touchedSides.add(side);
    trimRenderedRows(side);
  }

  for (const side of touchedSides) {
    const state = viewStates[side];
    syncEmptyState(side, state.matchingCount);
    updateCount(side, state.matchingCount);
    if (viewStates[side].viewport.isFollowing()) scrollToBottom(side);
  }
};

const scheduleUserIntentReset = (side: LogSide, delay = 160): void => {
  const state = viewStates[side];
  if (state.userIntentTimer !== null) window.clearTimeout(state.userIntentTimer);
  state.userIntentTimer = window.setTimeout(() => {
    state.userIntentTimer = null;
    state.viewport.endUserScroll();
  }, delay);
};

const beginMomentaryUserScroll = (side: LogSide, delay?: number): void => {
  viewStates[side].viewport.beginUserScroll();
  scheduleUserIntentReset(side, delay);
};

const setupScrollTracking = (side: LogSide): void => {
  const sideElements = elements[side];
  const state = viewStates[side];

  sideElements.list.addEventListener("wheel", () => beginMomentaryUserScroll(side), {
    passive: true,
  });
  sideElements.list.addEventListener("keydown", (event) => {
    if (USER_SCROLL_KEYS.has(event.key)) beginMomentaryUserScroll(side);
  });
  sideElements.list.addEventListener("pointerdown", () => {
    state.viewport.beginUserScroll();
  });
  window.addEventListener("pointerup", () => state.viewport.endUserScroll());
  window.addEventListener("pointercancel", () => state.viewport.endUserScroll());
  sideElements.list.addEventListener("touchstart", () => {
    state.viewport.beginUserScroll();
  }, { passive: true });
  sideElements.list.addEventListener("touchend", () => {
    scheduleUserIntentReset(side, 300);
  }, { passive: true });
  sideElements.list.addEventListener("scroll", () => {
    const distance = sideElements.list.scrollHeight
      - sideElements.list.scrollTop
      - sideElements.list.clientHeight;
    if (state.viewport.handleScroll(distance)) {
      sideElements.autoscroll.checked = false;
    }
  });

  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(() => {
      if (state.viewport.isFollowing()) scrollToBottom(side);
    });
    observer.observe(sideElements.list);
    resizeObservers.push(observer);
  }
};

const setupControls = (): void => {
  search.addEventListener("input", rebuildAll);
  pauseButton.addEventListener("click", () => {
    if (!model) return;
    const paused = !model.isPaused();
    model.setPaused(paused);
    pauseButton.textContent = paused ? "继续刷新" : "暂停刷新";
    pauseButton.setAttribute("aria-pressed", String(paused));
    status.textContent = paused ? "界面已暂停，日志仍在持续写入文件" : "实时日志流已连接";
    if (!paused) rebuildAll();
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
    const state = viewStates[side];
    sideElements.level.addEventListener("change", () => rebuildSide(side));
    sideElements.source.addEventListener("change", () => rebuildSide(side));
    sideElements.autoscroll.addEventListener("change", () => {
      state.viewport.setFollowing(sideElements.autoscroll.checked);
      if (state.viewport.isFollowing()) scrollToBottom(side);
    });
    setupScrollTracking(side);
    sideElements.clear.addEventListener("click", () => {
      void window.desktopPetApi.clearLogBuffer(side).then(() => {
        model?.clear(side);
        rebuildSide(side);
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
    appendIncomingRecords(batch.records);
  });
  window.addEventListener("beforeunload", () => {
    unsubscribe();
    for (const observer of resizeObservers) observer.disconnect();
  }, { once: true });

  const snapshot = await window.desktopPetApi.getLogSnapshot();
  model = new LogViewerModel(snapshot);
  model.append(earlyRecords);
  acceptingEarly = false;
  setupControls();
  rebuildAll();
  status.textContent = "实时日志流已连接";
};

void start().catch((error: unknown) => {
  status.textContent = error instanceof Error ? error.message : "日志控制台初始化失败";
});
