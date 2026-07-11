import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CONTEXT_STRATEGY_FIELDS,
  getContextStrategyMinimum,
} from "../src/settings/pages/context-strategy-page.js";

test("上下文策略页面固定展示五个参数", () => {
  assert.deepEqual(CONTEXT_STRATEGY_FIELDS, [
    "recent_context_human_messages",
    "max_images_in_context",
    "image_ttl_human_messages",
    "max_screenshots_in_context",
    "screenshot_ttl_human_messages",
  ]);
});

test("上下文轮数至少为 1，其余策略参数允许为 0", () => {
  assert.equal(getContextStrategyMinimum("recent_context_human_messages"), 1);
  assert.equal(getContextStrategyMinimum("max_images_in_context"), 0);
});
