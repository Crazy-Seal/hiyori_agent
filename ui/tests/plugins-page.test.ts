import assert from "node:assert/strict";
import { test } from "node:test";

import { getNumberFieldMinimum } from "../src/settings/pages/plugins-page.js";
import type { PluginItem } from "../shared-types.js";

const memoryPlugin: PluginItem = {
  name: "memory",
  description: "记忆",
  inherent: true,
  default_config: {
    summary_every_human_messages: 10,
  },
  config_schema: {
    properties: {
      summary_every_human_messages: { type: "integer", minimum: 1 },
    },
  },
};

test("插件数字字段最小值来自后端 JSON schema", () => {
  assert.equal(
    getNumberFieldMinimum(memoryPlugin, "summary_every_human_messages"),
    1
  );
});

test("插件数字字段缺少 schema minimum 时回退到 0", () => {
  assert.equal(getNumberFieldMinimum(memoryPlugin, "unknown_number"), 0);
});
