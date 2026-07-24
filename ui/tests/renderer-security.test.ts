import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createTrustedRendererPolicy,
  describeRendererUrl,
  isTrustedIpcSender,
  isTrustedRendererUrl,
} from "../electron/renderer-security.js";

test("生产策略只允许明确列出的本地页面", () => {
  const policy = createTrustedRendererPolicy({
    productionEntryUrls: [
      "file:///C:/Ayaya/dist/index.html",
      "file:///C:/Ayaya/dist/settings.html",
      "file:///C:/Ayaya/dist/logs.html",
    ],
  });

  assert.equal(isTrustedRendererUrl("file:///C:/Ayaya/dist/index.html", policy), true);
  assert.equal(isTrustedRendererUrl("file:///C:/Ayaya/dist/settings.html#llm", policy), true);
  assert.equal(isTrustedRendererUrl("file:///C:/Ayaya/dist/logs.html", policy), true);
  assert.equal(isTrustedRendererUrl("file:///C:/Ayaya/dist/other.html", policy), false);
  assert.equal(isTrustedRendererUrl("https://example.com", policy), false);
});

test("生产策略拒绝非本地入口和无法解析的目标", () => {
  assert.throws(
    () => createTrustedRendererPolicy({
      productionEntryUrls: ["https://example.com/index.html"],
    }),
    /本地 file URL/
  );
  const policy = createTrustedRendererPolicy({
    productionEntryUrls: ["file:///C:/Ayaya/dist/index.html"],
  });
  assert.equal(isTrustedRendererUrl("not-a-url", policy), false);
});

test("开发策略只允许环回 Vite origin 的应用页面", () => {
  const policy = createTrustedRendererPolicy({
    devServerUrl: "http://127.0.0.1:5173",
    productionEntryUrls: [],
  });

  assert.equal(isTrustedRendererUrl("http://127.0.0.1:5173/", policy), true);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:5173/index.html", policy), true);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:5173/settings.html", policy), true);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:5173/logs.html", policy), true);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:5173/admin.html", policy), false);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1.evil:5173/", policy), false);
  assert.equal(isTrustedRendererUrl("http://evil@127.0.0.1:5173/", policy), false);
});

test("非环回开发服务器配置被拒绝", () => {
  assert.throws(
    () => createTrustedRendererPolicy({
      devServerUrl: "http://192.168.1.20:5173",
      productionEntryUrls: [],
    }),
    /环回地址/
  );
});

test("开发服务器配置必须是纯 origin", () => {
  for (const devServerUrl of [
    "http://127.0.0.1:5173/app",
    "http://127.0.0.1:5173/?token=value",
    "http://127.0.0.1:5173/#fragment",
  ]) {
    assert.throws(
      () => createTrustedRendererPolicy({ devServerUrl, productionEntryUrls: [] }),
      /纯 origin/
    );
  }
});

test("IPC 只接受可信顶层 frame", () => {
  const policy = createTrustedRendererPolicy({
    devServerUrl: "http://127.0.0.1:5173",
    productionEntryUrls: [],
  });

  assert.equal(isTrustedIpcSender({
    url: "http://127.0.0.1:5173/settings.html",
    isMainFrame: true,
  }, policy), true);
  assert.equal(isTrustedIpcSender({
    url: "http://127.0.0.1:5173/settings.html",
    isMainFrame: false,
  }, policy), false);
  assert.equal(isTrustedIpcSender({
    url: "https://example.com/settings.html",
    isMainFrame: true,
  }, policy), false);
  assert.equal(isTrustedIpcSender(null, policy), false);
});

test("安全日志描述不包含查询参数、片段或非 Web URL 内容", () => {
  assert.equal(
    describeRendererUrl("https://user:secret@example.com/path?token=secret#fragment"),
    "https://example.com/path"
  );
  assert.equal(describeRendererUrl("data:text/html,secret"), "data:");
  assert.equal(describeRendererUrl("not-a-url"), "invalid-url");
});
