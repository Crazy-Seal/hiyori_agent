import assert from "node:assert/strict";
import { test } from "node:test";

import {
  appendErrorMessage,
  SettingsToast,
  type SettingsToastTimer,
} from "../src/settings/components/settings-toast.js";

type FakeToastElement = {
  hidden: boolean;
  textContent: string;
  dataset: Record<string, string>;
  querySelector(selector: string): FakeTextElement | FakePathElement | null;
};

type FakeTextElement = { textContent: string };
type FakePathElement = { pathData: string; setAttribute(name: string, value: string): void };

class FakeTimer implements SettingsToastTimer {
  private nextId = 1;
  private callbacks = new Map<number, () => void>();
  delays: number[] = [];

  setTimeout(callback: () => void, delayMs: number): unknown {
    const id = this.nextId++;
    this.callbacks.set(id, callback);
    this.delays.push(delayMs);
    return id;
  }

  clearTimeout(handle: unknown): void {
    this.callbacks.delete(Number(handle));
  }

  run(handle: number): void {
    const callback = this.callbacks.get(handle);
    this.callbacks.delete(handle);
    callback?.();
  }

  get pendingHandles(): number[] {
    return [...this.callbacks.keys()];
  }
}

const createToast = (): {
  toast: SettingsToast;
  element: FakeToastElement;
  messageElement: FakeTextElement;
  iconPath: FakePathElement;
  timer: FakeTimer;
} => {
  const messageElement: FakeTextElement = { textContent: "" };
  const iconPath: FakePathElement = {
    pathData: "",
    setAttribute(name, value) {
      if (name === "d") {
        this.pathData = value;
      }
    },
  };
  const element: FakeToastElement = {
    hidden: true,
    textContent: "",
    dataset: {},
    querySelector: (selector) => {
      if (selector === ".settings-toast-message") {
        return messageElement;
      }
      if (selector === ".settings-toast-icon path") {
        return iconPath;
      }
      return null;
    },
  };
  const timer = new FakeTimer();
  return {
    toast: new SettingsToast(element as unknown as HTMLDivElement, timer),
    element,
    messageElement,
    iconPath,
    timer,
  };
};

test("成功和失败提示带有对应标记并在 3 秒后隐藏", () => {
  const { toast, element, messageElement, iconPath, timer } = createToast();

  toast.success("修改成功");
  assert.equal(element.hidden, false);
  assert.equal(messageElement.textContent, "修改成功");
  const successPath = iconPath.pathData;
  assert.notEqual(successPath, "");
  assert.equal(element.dataset.variant, "success");
  assert.deepEqual(timer.delays, [3000]);

  timer.run(timer.pendingHandles[0]);
  assert.equal(element.hidden, true);
  assert.equal(messageElement.textContent, "");

  toast.error("修改失败：后端不可用");
  assert.equal(messageElement.textContent, "修改失败：后端不可用");
  assert.notEqual(iconPath.pathData, successPath);
  assert.equal(element.dataset.variant, "error");
});

test("新提示替换旧提示并重新开始计时", () => {
  const { toast, element, messageElement, timer } = createToast();

  toast.error("第一次失败");
  const firstHandle = timer.pendingHandles[0];
  toast.success("第二次成功");

  assert.deepEqual(timer.pendingHandles, [firstHandle + 1]);
  assert.equal(messageElement.textContent, "第二次成功");
  assert.equal(element.dataset.variant, "success");

  timer.run(firstHandle);
  assert.equal(element.hidden, false);
  timer.run(timer.pendingHandles[0]);
  assert.equal(element.hidden, true);
});

test("失败信息仅在后端提供原因时追加详情", () => {
  assert.equal(appendErrorMessage("修改失败", new Error("后端不可用")), "修改失败：后端不可用");
  assert.equal(appendErrorMessage("修改失败", undefined), "修改失败");
  assert.equal(appendErrorMessage("修改失败", "  "), "修改失败");
});

test("后端未启动时将 Electron fetch 错误转换为友好提示", () => {
  const error = new Error(
    "Error invoking remote method 'desktop-pet:get-available-tools': TypeError: fetch failed"
  );

  assert.equal(appendErrorMessage("读取工具列表失败", error), "读取工具列表失败：未识别到后端");
});

test("dispose 清理提示和待执行计时器", () => {
  const { toast, element, messageElement, timer } = createToast();

  toast.success("保存成功");
  toast.dispose();

  assert.deepEqual(timer.pendingHandles, []);
  assert.equal(element.hidden, true);
  assert.equal(messageElement.textContent, "");
});
