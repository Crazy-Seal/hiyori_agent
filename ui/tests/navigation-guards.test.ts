import assert from "node:assert/strict";
import { test } from "node:test";

import { installNavigationGuards } from "../electron/navigation-guards.js";

type NavigationListener = (event: { preventDefault(): void }, url: string) => void;

class FakeWebContents {
  readonly listeners = new Map<string, NavigationListener>();
  openHandler: ((details: { url: string }) => { action: "deny" }) | null = null;

  on(event: string, listener: NavigationListener): void {
    this.listeners.set(event, listener);
  }

  setWindowOpenHandler(handler: (details: { url: string }) => { action: "deny" }): void {
    this.openHandler = handler;
  }
}

test("导航守卫阻止不可信导航和重定向", () => {
  const webContents = new FakeWebContents();
  const blocked: Array<{ kind: string; url: string }> = [];
  installNavigationGuards(
    webContents,
    (url) => url.startsWith("file:///trusted/"),
    (kind, url) => blocked.push({ kind, url })
  );

  let prevented = false;
  webContents.listeners.get("will-navigate")?.({ preventDefault: () => { prevented = true; } }, "https://evil.example/");
  assert.equal(prevented, true);

  prevented = false;
  webContents.listeners.get("will-redirect")?.({ preventDefault: () => { prevented = true; } }, "file:///trusted/index.html");
  assert.equal(prevented, false);
  assert.deepEqual(blocked, [{ kind: "导航", url: "https://evil.example/" }]);
});

test("导航守卫拒绝 renderer 创建新窗口", () => {
  const webContents = new FakeWebContents();
  const blocked: Array<{ kind: string; url: string }> = [];
  installNavigationGuards(
    webContents,
    () => true,
    (kind, url) => blocked.push({ kind, url })
  );

  assert.deepEqual(webContents.openHandler?.({ url: "https://example.com/" }), { action: "deny" });
  assert.deepEqual(blocked, [{ kind: "新窗口", url: "https://example.com/" }]);
});
