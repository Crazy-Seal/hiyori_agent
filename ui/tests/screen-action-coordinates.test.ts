import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveScreenActionPoint } from "../electron/screen-action-coordinates.js";
import type { ControlScreenCoordinates } from "../shared-types.js";

const coordinates: ControlScreenCoordinates = {
  bbox: [450, 480, 580, 550],
  x_ratio: 986.5 / 1920,
  y_ratio: 555.5 / 1080,
  x: 987,
  y: 556,
  width: 1920,
  height: 1080,
};

test("屏幕操作优先使用截图像素坐标，避免 125% DPI 缩放导致 0.8 倍偏移", () => {
  const point = resolveScreenActionPoint(coordinates, {
    x: 0,
    y: 0,
    width: 1536,
    height: 864,
  });

  assert.deepEqual(point, { x: 987, y: 556 });
});

test("缺少截图像素坐标时才回退到比例坐标和显示器 bounds", () => {
  const point = resolveScreenActionPoint(
    {
      ...coordinates,
      x: Number.NaN,
      y: Number.NaN,
    },
    {
      x: 100,
      y: 50,
      width: 1536,
      height: 864,
    },
  );

  assert.deepEqual(point, { x: 889, y: 494 });
});
