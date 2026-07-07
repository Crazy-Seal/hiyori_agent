import assert from "node:assert/strict";
import { test } from "node:test";

import { getNumberFieldMinimum } from "../src/settings/pages/plugins-page.js";
import type { PluginItem } from "../shared-types.js";

const contextWindowPlugin: PluginItem = {
  name: "context_window",
  description: "上下文窗口",
  inherent: true,
  default_config: {
    recent_context_human_messages: 10,
    max_images_in_context: 5,
  },
  config_schema: {
    properties: {
      recent_context_human_messages: { type: "integer", minimum: 1 },
      max_images_in_context: { type: "integer", minimum: 0 },
    },
  },
};

test("插件数字字段最小值来自后端 JSON schema", () => {
  assert.equal(
    getNumberFieldMinimum(contextWindowPlugin, "recent_context_human_messages"),
    1
  );
  assert.equal(getNumberFieldMinimum(contextWindowPlugin, "max_images_in_context"), 0);
});

test("插件数字字段缺少 schema minimum 时回退到 0", () => {
  assert.equal(getNumberFieldMinimum(contextWindowPlugin, "unknown_number"), 0);
});
