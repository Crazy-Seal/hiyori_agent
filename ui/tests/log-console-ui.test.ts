import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const readUiFile = (relativePath: string): string =>
  readFileSync(relativePath, "utf8");

test("设置侧栏将日志入口放在独立紧凑工具区", () => {
  const html = readUiFile("settings.html");
  const utilitySection = html.match(
    /<div class="settings-utility-section">[\s\S]*?<\/div>/,
  )?.[0];

  assert.ok(utilitySection, "缺少设置侧栏独立工具区");
  assert.match(utilitySection, /id="open-log-window-btn"/);
  assert.match(utilitySection, /aria-label="打开日志控制台"/);
  assert.match(utilitySection, /<svg[^>]*aria-hidden="true"/);
  assert.match(utilitySection, />\s*日志\s*<\/button>/);
  assert.doesNotMatch(utilitySection, />\s*日志控制台\s*<\/button>/);
});

test("日志窗口复用设置标题栏并使用阈值级别选项", () => {
  const html = readUiFile("logs.html");

  assert.match(html, /class="settings-titlebar log-titlebar"/);
  assert.match(html, /class="settings-title log-title"/);
  assert.match(html, /aria-label="最小化">─<\/button>/);
  assert.match(html, /aria-label="关闭">✕<\/button>/);
  assert.match(html, /<option value="debug">DEBUG<\/option>/);
  assert.match(html, /<option value="info">INFO<\/option>/);
  assert.match(html, /<option value="warn">WARNING<\/option>/);
  assert.match(html, /<option value="error">ERROR<\/option>/);
  assert.match(html, /class="panel-btn panel-btn-danger[^"]*ui-button--danger/);
});

test("设置页与日志页共同使用窗口视觉基础样式", () => {
  const sharedCss = readUiFile("src/window-theme.css");
  const componentsCss = readUiFile("src/window-components.css");
  const settingsCss = readUiFile("src/settings.css");
  const logsCss = readUiFile("src/logs/logs.css");

  assert.match(settingsCss, /@import "\.\/window-components\.css";/);
  assert.match(logsCss, /@import "\.\.\/window-components\.css";/);
  assert.match(componentsCss, /@import "\.\/window-theme\.css";/);
  assert.match(sharedCss, /color-scheme:\s*dark/);
  assert.match(componentsCss, /\.ui-button:active/);
  assert.match(componentsCss, /:focus-visible/);
  assert.match(sharedCss, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(logsCss, /--color-primary:/);
});

test("日志列表使用可聚焦底部锚点和增量渲染而非每批整表重建", () => {
  const html = readUiFile("logs.html");
  const viewer = readUiFile("src/logs/log-viewer.ts");
  const css = readUiFile("src/logs/logs.css");

  assert.match(html, /id="frontend-logs"[^>]*tabindex="0"/);
  assert.match(html, /id="backend-logs"[^>]*tabindex="0"/);
  assert.match(viewer, /appendIncomingRecords/);
  assert.match(viewer, /syncEmptyState/);
  assert.match(viewer, /dataset\.recordId/);
  assert.match(viewer, /log-bottom-anchor/);
  assert.doesNotMatch(
    viewer,
    /model\?\.append\(batch\.records\);\s*if \(!model\?\.isPaused\(\)\) renderAll\(\);/,
  );
  assert.doesNotMatch(css, /content-visibility:\s*auto/);
  assert.doesNotMatch(css, /contain-intrinsic-size:/);
});
