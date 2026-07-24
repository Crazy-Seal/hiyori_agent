import assert from "node:assert/strict";
import { test } from "node:test";

import { LogViewerModel } from "../src/logs/log-viewer-model.js";
import type { LogRecord } from "../shared-types.js";

const record = (
  id: number,
  side: "frontend" | "backend",
  level: "debug" | "info" | "warn" | "error" = "info",
  message = `message-${id}`,
): LogRecord => ({
  id,
  timestamp: new Date(id * 1000).toISOString(),
  side,
  source: side === "frontend" ? "renderer" : "stderr",
  level,
  scope: "test",
  message,
});

test("查看器合并快照和实时批次时按 ID 去重并限制记录数", () => {
  const model = new LogViewerModel({
    frontend: [record(1, "frontend"), record(2, "frontend")],
    backend: [],
  }, 2);

  model.append([record(2, "frontend"), record(3, "frontend")]);

  assert.deepEqual(model.getRecords("frontend").map((item) => item.id), [2, 3]);
});

test("暂停期间保留新日志，继续后一次性应用", () => {
  const model = new LogViewerModel({ frontend: [], backend: [] }, 10);
  model.setPaused(true);
  model.append([record(1, "backend")]);
  assert.deepEqual(model.getRecords("backend"), []);

  model.setPaused(false);
  assert.deepEqual(model.getRecords("backend").map((item) => item.id), [1]);
});

test("暂停期间清空视图不会在继续时恢复已清除日志", () => {
  const model = new LogViewerModel({ frontend: [], backend: [] }, 10);
  model.setPaused(true);
  model.append([record(1, "backend")]);
  model.clear("backend");
  model.setPaused(false);

  assert.deepEqual(model.getRecords("backend"), []);
});

test("查看器按最低级别、文本和来源组合过滤", () => {
  const model = new LogViewerModel({
    frontend: [
      { ...record(1, "frontend", "info", "request started"), source: "electron-main" },
      { ...record(2, "frontend", "warn", "request slow"), source: "electron-main" },
      { ...record(3, "frontend", "error", "request failed"), source: "electron-main" },
      record(4, "frontend", "error", "renderer request failed"),
    ],
    backend: [],
  }, 10);

  const filtered = model.filter("frontend", {
    query: "REQUEST",
    minimumLevel: "warn",
    sources: new Set(["electron-main"]),
  });

  assert.deepEqual(filtered.map((item) => item.id), [2, 3]);
});

test("查看器按 DEBUG、INFO、WARN、ERROR 阈值逐级收窄结果", () => {
  const model = new LogViewerModel({
    frontend: [
      record(1, "frontend", "debug"),
      record(2, "frontend", "info"),
      record(3, "frontend", "warn"),
      record(4, "frontend", "error"),
    ],
    backend: [],
  }, 10);

  const idsAt = (minimumLevel: "debug" | "info" | "warn" | "error") =>
    model.filter("frontend", {
      query: "",
      minimumLevel,
      sources: new Set(),
    }).map((item) => item.id);

  assert.deepEqual(idsAt("debug"), [1, 2, 3, 4]);
  assert.deepEqual(idsAt("info"), [2, 3, 4]);
  assert.deepEqual(idsAt("warn"), [3, 4]);
  assert.deepEqual(idsAt("error"), [4]);
});
