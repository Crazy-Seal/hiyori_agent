import assert from "node:assert/strict";
import { test } from "node:test";

import { ConfirmDialog } from "../src/settings/components/confirm-dialog.js";

class FakeClassList {
  private readonly values = new Set<string>();

  add(...tokens: string[]): void {
    tokens.forEach((token) => this.values.add(token));
  }

  remove(...tokens: string[]): void {
    tokens.forEach((token) => this.values.delete(token));
  }

  contains(token: string): boolean {
    return this.values.has(token);
  }
}

class FakeElement extends EventTarget {
  hidden = true;
  textContent = "";
  readonly classList = new FakeClassList();
  private readonly attributes = new Map<string, string>();

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }
}

const createDialog = () => {
  const dialog = new FakeElement();
  const cancel = new FakeElement();
  const ok = new FakeElement();
  const title = new FakeElement();
  const message = new FakeElement();
  const instance = new ConfirmDialog(
    dialog as unknown as HTMLDivElement,
    cancel as unknown as HTMLButtonElement,
    ok as unknown as HTMLButtonElement,
    title as unknown as HTMLElement,
    message as unknown as HTMLElement
  );
  return { instance, dialog, cancel, ok, title, message };
};

test("确认框可动态展示 HTTP 风险警告", async () => {
  const { instance, dialog, ok, title, message } = createDialog();
  const result = instance.open({
    title: "未加密连接警告",
    message: "API Key 将发送到 http://example.com/v1",
    confirmText: "仍然保存",
    cancelText: "取消",
    variant: "warning",
  });

  assert.equal(dialog.hidden, false);
  assert.equal(dialog.getAttribute("aria-hidden"), "false");
  assert.equal(title.textContent, "未加密连接警告");
  assert.match(message.textContent, /http:\/\/example\.com\/v1/);
  assert.equal(ok.textContent, "仍然保存");
  assert.equal(ok.classList.contains("confirm-btn-warning"), true);

  ok.dispatchEvent(new Event("click"));
  assert.equal(await result, true);
  assert.equal(dialog.hidden, true);
});

test("确认框取消时返回 false，并切换回危险操作样式", async () => {
  const { instance, cancel, ok } = createDialog();
  const result = instance.open({
    title: "删除模型确认",
    message: "删除后无法恢复",
    confirmText: "确认删除",
    cancelText: "取消",
    variant: "danger",
  });

  assert.equal(ok.classList.contains("confirm-btn-danger"), true);
  assert.equal(ok.classList.contains("confirm-btn-warning"), false);
  cancel.dispatchEvent(new Event("click"));
  assert.equal(await result, false);
});
