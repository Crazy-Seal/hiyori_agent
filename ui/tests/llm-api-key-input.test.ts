import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { bindPressToRevealSecret } from "../src/settings/components/press-to-reveal-secret.js";

test("LLM API Key 输入框默认使用密码掩码显示", () => {
  const settingsHtml = readFileSync("settings.html", "utf8");
  const apiKeyInput = settingsHtml.match(/<input\s+[^>]*id="llm-api-key"[^>]*>/)?.[0];

  assert.ok(apiKeyInput, "缺少 LLM API Key 输入框");
  assert.match(apiKeyInput, /\btype="password"/);
  assert.match(apiKeyInput, /\bname="openai_api_key"/);
  assert.match(
    settingsHtml,
    /<label\s+[^>]*for="llm-api-key"[^>]*>\s*API Key\s*<\/label>/
  );
  assert.match(settingsHtml, /<button\s+[^>]*id="llm-api-key-reveal"[^>]*>/);
});

test("仅在按住查看按钮时显示密钥，松开或失焦后立即恢复掩码", () => {
  const input = { type: "password" };
  const button = new EventTarget();
  const windowTarget = new EventTarget();
  const dispatchPointer = (target: EventTarget, type: string, mouseButton = 0): void => {
    const event = new Event(type);
    Object.defineProperty(event, "button", { value: mouseButton });
    target.dispatchEvent(event);
  };
  const unbind = bindPressToRevealSecret(
    input as HTMLInputElement,
    button as HTMLButtonElement,
    windowTarget
  );

  dispatchPointer(button, "pointerdown", 2);
  assert.equal(input.type, "password");

  dispatchPointer(button, "pointerdown");
  assert.equal(input.type, "text");
  dispatchPointer(windowTarget, "pointerup");
  assert.equal(input.type, "password");

  dispatchPointer(button, "pointerdown");
  button.dispatchEvent(new Event("pointerleave"));
  assert.equal(input.type, "password");

  dispatchPointer(button, "pointerdown");
  windowTarget.dispatchEvent(new Event("blur"));
  assert.equal(input.type, "password");

  unbind();
});
