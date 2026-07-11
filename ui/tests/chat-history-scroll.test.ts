import assert from "node:assert/strict";
import { test } from "node:test";

import { ChatHistoryManager } from "../src/chat/chat-history-manager.js";

class FakeElement {
  className = "";
  textContent = "";
  children: FakeElement[] = [];

  appendChild(child: FakeElement): FakeElement {
    this.children.push(child);
    return child;
  }

  remove(): void {}
}

class FakeContainer extends FakeElement {
  scrollHeight = 100;
  scrollCalls: ScrollToOptions[] = [];

  scrollTo(options: ScrollToOptions): void {
    this.scrollCalls.push(options);
  }
}

test("流结束时逐条追加剩余气泡并逐条滚动到底部", () => {
  const originalDocument = globalThis.document;
  const container = new FakeContainer();
  globalThis.document = {
    createElement: () => new FakeElement(),
  } as unknown as Document;

  try {
    const manager = new ChatHistoryManager(container as unknown as HTMLDivElement);
    manager.startStreaming();
    manager.updateLastAiMessage("第一句。第二句。第三句。");
    manager.finalizeStreamingMessage();

    assert.equal(container.children.length, 3);
    assert.equal(container.scrollCalls.length, 3);
  } finally {
    globalThis.document = originalDocument;
  }
});
