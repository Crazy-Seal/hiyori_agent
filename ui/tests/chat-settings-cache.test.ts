import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  clearChatSettingsCache,
  getDefaultAgentPluginsForTest,
  getChatSettingsCache,
  updateChatSettings,
  updateChatSettingsCache,
} from "../electron/chat-settings.js";
import type { ChatSettingsData } from "../shared-types.js";

const originalFetch = globalThis.fetch;

const savedSettings: ChatSettingsData = {
  session_id: "saved-session",
  model_name: "saved-model",
  openai_api_key: "saved-key",
  openai_base_url: "http://saved.example/v1",
  temperature: 0.7,
  system_prompt: "saved prompt",
  tools_list: [],
};

afterEach(() => {
  globalThis.fetch = originalFetch;
  clearChatSettingsCache();
});

test("PUT 失败时保留最后一次成功的 ChatSettings 缓存", async () => {
  updateChatSettingsCache(savedSettings);
  globalThis.fetch = async () => new Response("backend unavailable", { status: 503 });

  const attemptedSettings: ChatSettingsData = {
    ...savedSettings,
    model_name: "unsaved-model",
  };

  await assert.rejects(updateChatSettings(attemptedSettings));
  assert.deepEqual(getChatSettingsCache(), savedSettings);
});

test("PUT 成功后更新 ChatSettings 缓存", async () => {
  updateChatSettingsCache(savedSettings);
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: 200, msg: "success" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  const updatedSettings: ChatSettingsData = {
    ...savedSettings,
    model_name: "updated-model",
  };

  await updateChatSettings(updatedSettings);
  assert.deepEqual(getChatSettingsCache(), updatedSettings);
});

test("前端默认 memory 插件为固有启用", () => {
  const defaults = getDefaultAgentPluginsForTest();

  assert.equal(defaults.context_window.enabled, true);
  assert.equal(defaults.memory.enabled, true);
});
