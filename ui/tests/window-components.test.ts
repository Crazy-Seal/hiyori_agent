import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const readUiFile = (relativePath: string): string =>
  readFileSync(relativePath, "utf8");

const elementById = (html: string, id: string): string => {
  const element = html.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0];
  assert.ok(element, `缺少元素 #${id}`);
  return element;
};

const assertHasClasses = (
  html: string,
  id: string,
  expectedClasses: readonly string[],
): void => {
  const element = elementById(html, id);
  const classNames = element.match(/class="([^"]+)"/)?.[1]?.split(/\s+/) ?? [];

  for (const expectedClass of expectedClasses) {
    assert.ok(
      classNames.includes(expectedClass),
      `#${id} 缺少共享样式类 ${expectedClass}`,
    );
  }
};

test("设置页和日志页共同引用窗口组件样式层", () => {
  const settingsCss = readUiFile("src/settings.css");
  const logsCss = readUiFile("src/logs/logs.css");
  const componentsCss = readUiFile("src/window-components.css");

  assert.match(settingsCss, /@import "\.\/window-components\.css";/);
  assert.match(logsCss, /@import "\.\.\/window-components\.css";/);
  assert.match(componentsCss, /@import "\.\/window-theme\.css";/);
});

test("共享组件覆盖语义按钮、表单控件和完整交互状态", () => {
  const css = readUiFile("src/window-components.css");

  for (const selector of [
    ".ui-button",
    ".ui-button--primary",
    ".ui-button--danger",
    ".ui-button--secondary",
    ".ui-button--warning",
    ".ui-button--icon",
    ".ui-button--small",
    ".ui-button--medium",
    ".ui-control",
    ".ui-select",
    ".ui-checkbox",
    ".ui-range",
    ".ui-surface",
    ".ui-table",
    ".ui-dialog",
    ".ui-toast",
    ".ui-empty-state",
  ]) {
    assert.match(css, new RegExp(`\\${selector}\\b`), `缺少 ${selector}`);
  }

  assert.match(css, /\.ui-button:hover/);
  assert.match(css, /\.ui-button:active/);
  assert.match(css, /\.ui-button:focus-visible/);
  assert.match(css, /\.ui-button:disabled/);
  assert.match(css, /\.ui-checkbox:hover/);
  assert.match(css, /\.ui-checkbox:checked/);
  assert.match(css, /\.ui-checkbox:focus-visible/);
  assert.match(css, /\.ui-checkbox:disabled/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
});

test("窗口静态控件使用统一语义类", () => {
  const settingsHtml = readUiFile("settings.html");
  const logsHtml = readUiFile("logs.html");

  for (const id of [
    "settings-min-btn",
    "settings-close-btn",
    "open-log-window-btn",
    "import-model-btn",
    "confirm-import-btn",
    "cancel-import-btn",
    "llm-confirm-btn",
    "motion-confirm-btn",
    "plugins-confirm-btn",
    "context-strategy-confirm-btn",
    "tools-confirm-btn",
    "mcp-add-btn",
    "mcp-policy-save-btn",
    "mcp-test-btn",
    "mcp-save-btn",
    "mcp-cancel-btn",
    "delete-confirm-cancel",
    "delete-confirm-ok",
  ]) {
    assertHasClasses(settingsHtml, id, ["ui-button"]);
  }

  assertHasClasses(settingsHtml, "settings-close-btn", ["ui-button--danger"]);
  assertHasClasses(settingsHtml, "import-model-btn", ["ui-button--primary"]);
  assertHasClasses(settingsHtml, "open-log-window-btn", ["ui-button--primary"]);
  assertHasClasses(settingsHtml, "delete-confirm-ok", ["ui-button--danger"]);
  assertHasClasses(settingsHtml, "checkbox-follow-cursor", ["ui-checkbox"]);
  assertHasClasses(settingsHtml, "checkbox-hide-on-screenshot", ["ui-checkbox"]);
  assertHasClasses(settingsHtml, "mcp-transport", ["ui-control", "ui-select"]);

  for (const id of [
    "log-min-btn",
    "log-close-btn",
    "log-pause-btn",
    "open-log-directory-btn",
    "frontend-clear",
    "backend-clear",
  ]) {
    assertHasClasses(logsHtml, id, ["ui-button"]);
  }

  assertHasClasses(logsHtml, "log-close-btn", ["ui-button--danger"]);
  assertHasClasses(logsHtml, "open-log-directory-btn", ["ui-button--primary"]);
  assertHasClasses(logsHtml, "log-pause-btn", ["ui-button--secondary"]);
  assertHasClasses(logsHtml, "frontend-clear", ["ui-button--danger"]);
  assertHasClasses(logsHtml, "log-search", ["ui-control"]);
  assertHasClasses(logsHtml, "frontend-level", ["ui-control", "ui-select"]);
  assertHasClasses(logsHtml, "backend-autoscroll", ["ui-checkbox"]);
});

test("设置页动态生成的控件也使用共享组件类", () => {
  const modelPage = readUiFile("src/settings/pages/model-page.ts");
  const motionPage = readUiFile("src/settings/pages/motion-page.ts");
  const pluginsPage = readUiFile("src/settings/pages/plugins-page.ts");
  const toolsPage = readUiFile("src/settings/pages/tools-page.ts");
  const mcpPage = readUiFile("src/settings/pages/mcp-page.ts");

  assert.match(modelPage, /delete-model-btn ui-button ui-button--danger/);
  assert.match(motionPage, /motion-preview-btn ui-button ui-button--secondary/);
  assert.match(
    motionPage,
    /motion-setting-select ui-control ui-control--small ui-select/,
  );
  assert.match(pluginsPage, /ui-checkbox/);
  assert.match(toolsPage, /ui-checkbox/);
  assert.match(mcpPage, /variant: "secondary" \| "danger" = "secondary"/);
  assert.match(mcpPage, /ui-button ui-button--\$\{variant\} ui-button--small/);
  assert.match(mcpPage, /ui-control ui-control--small ui-select/);
});

test("MCP 空状态居中且保存权限按钮固定为左对齐", () => {
  const css = readUiFile("src/settings.css");

  assert.match(
    css,
    /\.mcp-page\s*\{[^}]*height:\s*100%;[^}]*box-sizing:\s*border-box;/s,
  );
  assert.match(
    css,
    /\.mcp-page\s*>\s*\.page-placeholder\s*\{[^}]*flex:\s*1;[^}]*width:\s*auto;[^}]*height:\s*auto;/s,
  );
  assert.match(
    css,
    /\.mcp-server-list\s*\{[^}]*flex:\s*1;[^}]*min-height:\s*0;[^}]*overflow:\s*auto;/s,
  );
  assert.match(
    css,
    /\.mcp-policy-save-btn\s*\{[^}]*align-self:\s*flex-start;/s,
  );
});

test("设置侧栏在固定窗口高度内使用紧凑页签并隔离溢出滚动", () => {
  const themeCss = readUiFile("src/window-theme.css");
  const settingsCss = readUiFile("src/settings.css");

  assert.match(themeCss, /html,\s*body\s*\{[^}]*overflow:\s*hidden;/s);
  assert.match(
    settingsCss,
    /\.settings-layout\s*\{[^}]*overflow:\s*hidden;/s,
  );
  assert.match(
    settingsCss,
    /\.settings-sidebar\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;/s,
  );
  assert.match(
    settingsCss,
    /\.settings-tab\s*\{[^}]*padding-block:\s*var\(--spacing-sm\);/s,
  );
});

test("共享下拉框显示清晰箭头并为原生选项提供主题样式", () => {
  const css = readUiFile("src/window-components.css");

  assert.doesNotMatch(
    css,
    /(?<!input)(?<!textarea)\.ui-control:read-only/,
    "通用只读规则会错误命中 select 并清除背景箭头",
  );
  assert.match(css, /input\.ui-control:read-only/);
  assert.match(css, /textarea\.ui-control:read-only/);
  assert.match(
    css,
    /\.ui-select\s*\{[^}]*background-image:\s*url\("data:image\/svg\+xml;base64,/s,
  );
  assert.match(
    css,
    /\.ui-select\s*\{[^}]*background-size:\s*14px 14px;/s,
  );
  const optionRule = css.match(/\.ui-select option\s*\{([^}]*)\}/s)?.[1] ?? "";
  assert.match(optionRule, /font-family:\s*var\(--font-family-body\);/);
  assert.match(
    optionRule,
    /background-color:\s*var\(--color-bg-elevated\);/,
  );
  assert.match(
    css,
    /\.ui-select option:checked\s*\{[^}]*background-color:\s*var\(--color-primary-dark\);/s,
  );
});

test("支持环境使用 base-select 美化按钮、Picker 和选项状态", () => {
  const css = readUiFile("src/window-components.css");
  const supportStart = css.indexOf("@supports (appearance: base-select)");

  assert.notEqual(supportStart, -1, "缺少 base-select 渐进增强块");
  const supportedCss = css.slice(supportStart);
  assert.match(
    supportedCss,
    /\.ui-select,\s*\.ui-select::picker\(select\)\s*\{[^}]*appearance:\s*base-select;/s,
  );
  assert.match(
    supportedCss,
    /\.ui-select\s*\{[^}]*background-image:\s*none;/s,
  );
  assert.match(supportedCss, /\.ui-select::picker-icon\s*\{/);
  assert.match(supportedCss, /\.ui-select:open::picker-icon\s*\{/);
  assert.match(
    supportedCss,
    /\.ui-select::picker\(select\)\s*\{[^}]*max-height:\s*min\(320px,\s*50vh\);/s,
  );
  assert.match(supportedCss, /\.ui-select option:hover/);
  assert.match(supportedCss, /\.ui-select option:focus/);
  assert.match(supportedCss, /\.ui-select option:checked/);
  assert.match(supportedCss, /\.ui-select option:disabled/);
  assert.match(supportedCss, /\.ui-select option::checkmark\s*\{/);
});

test("动态表情设置下拉框提供包含动作名称的可访问名称", () => {
  const motionPage = readUiFile("src/settings/pages/motion-page.ts");

  assert.match(
    motionPage,
    /select\.ariaLabel\s*=\s*`\$\{motionName\}\s*的动作设置`;/,
  );
});

test("Vite 生产构建使用相对资源路径供 Electron loadFile 加载", () => {
  const viteConfig = readUiFile("vite.config.ts");

  assert.match(viteConfig, /base:\s*["']\.\/["']/);
});
