import assert from "node:assert/strict";
import { test } from "node:test";

import {
  authorizeBaseUrlChange,
  classifyHttpEndpoint,
} from "../src/settings/url-security.js";

test("HTTPS 地址可直接保存", () => {
  assert.deepEqual(classifyHttpEndpoint("https://api.example.com/v1"), {
    kind: "safe",
    normalizedUrl: "https://api.example.com/v1",
  });
});

test("HTTP 环回地址可直接保存", () => {
  for (const url of [
    "http://localhost:8000/v1",
    "http://127.0.0.1:8000/v1",
    "http://127.255.12.34/v1",
    "http://[::1]:8000/v1",
  ]) {
    assert.equal(classifyHttpEndpoint(url).kind, "safe", url);
  }
});

test("非环回 HTTP 地址需要风险确认", () => {
  for (const url of [
    "http://192.168.1.20:8000/v1",
    "http://api.example.com/v1",
    "http://128.0.0.1/v1",
    "http://localhost.example.com/v1",
  ]) {
    assert.equal(classifyHttpEndpoint(url).kind, "insecure_http", url);
  }
});

test("非法地址、用户信息伪装和非 HTTP 协议被拒绝", () => {
  for (const url of [
    "not-a-url",
    "http://localhost@evil.example/v1",
    "ftp://example.com/v1",
    "file:///tmp/api",
  ]) {
    assert.equal(classifyHttpEndpoint(url).kind, "invalid", url);
  }
});

test("地址变更为非环回 HTTP 时由用户确认后继续", async () => {
  const prompted: string[] = [];
  const allowed = await authorizeBaseUrlChange({
    previousUrl: "https://api.example.com/v1",
    nextUrl: "http://192.168.1.20:8000/v1",
    confirmInsecure: async (url) => {
      prompted.push(url);
      return true;
    },
  });

  assert.equal(allowed, true);
  assert.deepEqual(prompted, ["http://192.168.1.20:8000/v1"]);
});

test("用户取消风险确认时终止保存", async () => {
  const allowed = await authorizeBaseUrlChange({
    previousUrl: "https://api.example.com/v1",
    nextUrl: "http://api.example.com/v1",
    confirmInsecure: async () => false,
  });

  assert.equal(allowed, false);
});

test("已保存的不安全地址未变化时不重复确认", async () => {
  let promptCount = 0;
  const allowed = await authorizeBaseUrlChange({
    previousUrl: "http://api.example.com/v1",
    nextUrl: "http://api.example.com/v1",
    confirmInsecure: async () => {
      promptCount += 1;
      return false;
    },
  });

  assert.equal(allowed, true);
  assert.equal(promptCount, 0);
});

test("空 Base URL 可直接保存", async () => {
  let promptCount = 0;
  const allowed = await authorizeBaseUrlChange({
    previousUrl: "https://api.example.com/v1",
    nextUrl: "",
    confirmInsecure: async () => {
      promptCount += 1;
      return false;
    },
  });

  assert.equal(allowed, true);
  assert.equal(promptCount, 0);
});

test("非法新地址在保存前抛出可读错误", async () => {
  await assert.rejects(
    authorizeBaseUrlChange({
      previousUrl: "https://api.example.com/v1",
      nextUrl: "invalid",
      confirmInsecure: async () => true,
    }),
    /有效的 HTTP 或 HTTPS 地址/
  );
});
