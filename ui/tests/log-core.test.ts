import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BackendLineDecoder,
  LogHub,
  inferBackendLevel,
  sanitizeLogMessage,
} from "../electron/logging/log-core.js";
import type { LogBatch } from "../shared-types.js";

test("日志脱敏会移除令牌、授权头、API Key 和图片 Base64", () => {
  const token = "secret-token-value";
  const input = [
    `AYAYA_API_TOKEN=${token}`,
    `Authorization: Bearer ${token}`,
    'openai_api_key="sk-sensitive"',
    "data:image/png;base64,AAAABBBBCCCC",
  ].join(" ");

  const result = sanitizeLogMessage(input, [token], 32 * 1024);

  assert.doesNotMatch(result, /secret-token-value|sk-sensitive|AAAABBBBCCCC/);
  assert.match(result, /\[REDACTED\]/);
});

test("日志消息超过限制时按 UTF-8 字节安全截断", () => {
  const result = sanitizeLogMessage("你".repeat(20), [], 24);

  assert.match(result, /已截断/);
  assert.doesNotMatch(result, /\uFFFD/);
});

test("LogHub 保留分侧环形缓存、批量发布并支持清空视图", async () => {
  const batches: LogBatch[] = [];
  const hub = new LogHub({ bufferLimit: 2, batchIntervalMs: 1 });
  hub.subscribe((batch) => batches.push(batch));

  hub.append({
    side: "frontend",
    source: "electron-main",
    level: "info",
    scope: "test",
    message: "one",
  });
  hub.append({
    side: "frontend",
    source: "renderer",
    level: "warn",
    scope: "test",
    message: "two",
  });
  hub.append({
    side: "frontend",
    source: "renderer",
    level: "error",
    scope: "test",
    message: "three",
  });

  await new Promise((resolve) => setTimeout(resolve, 10));

  assert.deepEqual(
    hub.getSnapshot().frontend.map((record) => record.message),
    ["two", "three"],
  );
  assert.deepEqual(
    batches.flatMap((batch) => batch.records).map((record) => record.message),
    ["one", "two", "three"],
  );

  hub.clear("frontend");
  assert.deepEqual(hub.getSnapshot().frontend, []);
  await hub.close();
});

test("清空视图会移除尚未发布的同侧批次", async () => {
  const batches: LogBatch[] = [];
  const hub = new LogHub({ batchIntervalMs: 1 });
  hub.subscribe((batch) => batches.push(batch));
  hub.append({
    side: "backend",
    source: "stderr",
    level: "info",
    scope: "test",
    message: "即将清空",
  });

  hub.clear("backend");
  await new Promise((resolve) => setTimeout(resolve, 10));

  assert.deepEqual(batches, []);
  await hub.close();
});

test("后端行解析器正确处理跨 chunk、CRLF 和退出残留", () => {
  const lines: string[] = [];
  const decoder = new BackendLineDecoder((line) => lines.push(line));

  decoder.write(Buffer.from("INFO: boot\r\nTrace"));
  decoder.write(Buffer.from("back line\nlast"));
  decoder.end();

  assert.deepEqual(lines, ["INFO: boot", "Traceback line", "last"]);
});

test("后端行解析器正确还原跨 chunk 的中文 UTF-8 字符", () => {
  const lines: string[] = [];
  const decoder = new BackendLineDecoder((line) => lines.push(line));
  const encoded = Buffer.from("INFO: 中文日志\r\n尾行", "utf8");
  const splitInsideFirstChineseCharacter = Buffer.byteLength("INFO: ", "utf8") + 1;

  decoder.write(encoded.subarray(0, splitInsideFirstChineseCharacter));
  decoder.write(encoded.subarray(splitInsideFirstChineseCharacter));
  decoder.end();

  assert.deepEqual(lines, ["INFO: 中文日志", "尾行"]);
});

test("Uvicorn stderr INFO 不会被误判为错误", () => {
  assert.equal(inferBackendLevel("INFO: Uvicorn running"), "info");
  assert.equal(inferBackendLevel("WARNING: slow request"), "warn");
  assert.equal(inferBackendLevel("ERROR: startup failed"), "error");
  assert.equal(inferBackendLevel("Traceback (most recent call last):"), "error");
  assert.equal(inferBackendLevel("2026-07-24 01:02:03 | WARNING | app.agent | slow"), "warn");
  assert.equal(inferBackendLevel("2026-07-24 01:02:03 | ERROR | app.agent | failed"), "error");
});
