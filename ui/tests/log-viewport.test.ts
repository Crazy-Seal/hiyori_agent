import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LogViewportState,
  resolveAnchoredScrollTop,
  selectRestorationAnchorId,
} from "../src/logs/log-viewport.js";

test("程序滚动和布局变化不会关闭自动滚动", () => {
  const state = new LogViewportState(true);

  assert.equal(state.handleScroll(300), false);
  assert.equal(state.isFollowing(), true);
});

test("只有明确的用户滚动离开底部才关闭自动滚动", () => {
  const state = new LogViewportState(true);

  state.beginUserScroll();
  assert.equal(state.handleScroll(12), false);
  assert.equal(state.isFollowing(), true);
  assert.equal(state.handleScroll(25), true);
  assert.equal(state.isFollowing(), false);
});

test("重新启用自动滚动后忽略旧的用户滚动状态", () => {
  const state = new LogViewportState(true);
  state.beginUserScroll();
  state.handleScroll(100);

  state.setFollowing(true);

  assert.equal(state.isFollowing(), true);
  assert.equal(state.handleScroll(100), false);
});

test("筛选重建优先恢复原记录，否则选择 ID 最近的后续记录", () => {
  const ids = [10, 20, 40];

  assert.equal(selectRestorationAnchorId(ids, 20), 20);
  assert.equal(selectRestorationAnchorId(ids, 25), 40);
  assert.equal(selectRestorationAnchorId(ids, 50), 40);
  assert.equal(selectRestorationAnchorId([], 20), undefined);
});

test("恢复阅读锚点时使用列表内相对位置而不是页面 offsetTop", () => {
  assert.equal(resolveAnchoredScrollTop(140, -130, -10), 20);
  assert.equal(resolveAnchoredScrollTop(10, -30, 5), 0);
});
