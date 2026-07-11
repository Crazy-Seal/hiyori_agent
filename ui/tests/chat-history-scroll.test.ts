import assert from "node:assert/strict";
import { test } from "node:test";

import { ChatHistoryManager } from "../src/chat/chat-history-manager.js";

class FakeElement {
  className = "";
  textContent = "";
  children: FakeElement[] = [];
  removed = false;

  appendChild(child: FakeElement): FakeElement {
    this.children.push(child);
    return child;
  }

  remove(): void {
    this.removed = true;
  }
}

class FakeContainer extends FakeElement {
  scrollHeight = 100;
  scrollCalls: ScrollToOptions[] = [];

  scrollTo(options: ScrollToOptions): void {
    this.scrollCalls.push(options);
  }
}

test("流结束后仍以 500ms 间隔逐条追加并滚动到底部", () => {
  const originalDocument = globalThis.document;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  const container = new FakeContainer();
  let intervalCallback: (() => void) | undefined;
  globalThis.document = {
    createElement: () => new FakeElement(),
  } as unknown as Document;
  globalThis.setInterval = ((callback: () => void, delay: number) => {
    assert.equal(delay, 500);
    intervalCallback = callback;
    return 1;
  }) as unknown as typeof setInterval;
  globalThis.clearInterval = (() => {}) as typeof clearInterval;

  try {
    const manager = new ChatHistoryManager(container as unknown as HTMLDivElement);
    manager.startStreaming();
    manager.updateLastAiMessage("第一句。第二句。第三句。");
    manager.finalizeStreamingMessage();

    assert.equal(container.children.length, 0);

    intervalCallback?.();
    assert.equal(container.children.length, 1);
    assert.equal(container.scrollCalls.length, 1);

    intervalCallback?.();
    assert.equal(container.children.length, 2);
    assert.equal(container.scrollCalls.length, 2);

    intervalCallback?.();
    assert.equal(container.children.length, 3);
    assert.equal(container.scrollCalls.length, 3);

    manager.startStreaming();
    assert.equal(container.children.some((child) => child.removed), false);
    manager.abortStreaming();
  } finally {
    globalThis.document = originalDocument;
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  }
});

test("上一轮尾句尚未显示完时启动新一轮会先完整输出旧回复", () => {
  const originalDocument = globalThis.document;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  const container = new FakeContainer();
  let intervalCallback: (() => void) | undefined;
  globalThis.document = {
    createElement: () => new FakeElement(),
  } as unknown as Document;
  globalThis.setInterval = ((callback: () => void) => {
    intervalCallback = callback;
    return 1;
  }) as unknown as typeof setInterval;
  globalThis.clearInterval = (() => {}) as typeof clearInterval;

  try {
    const manager = new ChatHistoryManager(container as unknown as HTMLDivElement);
    manager.startStreaming();
    manager.updateLastAiMessage("第一句。第二句。第三句。");
    manager.finalizeStreamingMessage();

    intervalCallback?.();
    assert.equal(container.children.length, 1);

    manager.startStreaming();

    assert.equal(container.children.length, 3);
    assert.equal(container.scrollCalls.length, 3);
    assert.equal(container.children.some((child) => child.removed), false);
    manager.abortStreaming();
  } finally {
    globalThis.document = originalDocument;
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  }
});
