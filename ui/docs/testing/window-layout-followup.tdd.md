# 设置页布局与下拉框修复：TDD 证据

## 用户旅程

- 作为用户，我希望 MCP 空状态真正居中，保存权限按钮保持紧凑并位于列表左下方。
- 作为用户，我希望设置侧栏在默认窗口高度内完整显示，必要滚动也只发生在侧栏内部。
- 作为用户，我希望下拉框具有清晰的展开提示，并与窗口深色主题保持一致。

## RED / GREEN

| 阶段 | 命令 | 结果 | 证据 |
|---|---|---|---|
| RED | `npm.cmd run test:unit` | FAIL | 原有 126 项通过；新增 3 项分别因 MCP 布局、侧栏溢出隔离和下拉框主题合同缺失而失败。 |
| GREEN 初检 | `npm.cmd run test:unit` | FAIL | 产品合同已有 2 项通过；下拉框测试因错误依赖 CSS 属性顺序而失败，已修正测试断言。 |
| GREEN | `npm.cmd run test:unit` | PASS | 129/129 项通过。 |
| Build | `npm.cmd run build` | PASS | TypeScript、Vite 多页面构建和 Electron preload 构建成功。 |
| Diff | `git diff --check` | PASS | 无空白错误；仅报告现有 Windows LF/CRLF 提示。 |
| Runtime RED | Electron 38 计算样式探针 | FAIL | `select` 错误匹配通用 `.ui-control:read-only`，高优先级 `background` 简写将箭头覆盖为 `background-image: none`。 |
| Runtime GREEN | Electron 38 计算样式探针 | PASS | 只读规则限定到 `input`/`textarea` 后，`select` 得到 Base64 SVG、14px 尺寸和正确文字颜色，实际截图可见橙色箭头。 |

## 测试规格

| 保证 | 测试 | 类型 | 结果 |
|---|---|---|---|
| MCP 页面占满内容区，空状态使用剩余空间居中 | `tests/window-components.test.ts` | 静态 UI 合同 | PASS |
| MCP 列表占用可用空间并独立滚动，保存按钮左对齐 | `tests/window-components.test.ts` | 静态 UI 合同 | PASS |
| 根页面不滚动，侧栏隔离溢出，页签在默认高度采用紧凑间距 | `tests/window-components.test.ts` | 静态 UI 合同 | PASS |
| 下拉框使用 14px SVG 箭头，原生选项具有字体、背景和选中配色 | `tests/window-components.test.ts` | 静态 UI 合同 | PASS |
| 通用只读规则不会再次误命中下拉框并清除背景箭头 | `tests/window-components.test.ts` | CSS 级联合同 | PASS |

## 已知边界

- 原生 `<select>` 的弹出菜单仍由 Chromium 和操作系统共同绘制，CSS 可以统一文字、背景及选中配色，但不能像自定义 listbox 一样控制所有圆角、阴影和逐项动画。
- 本次没有启动 Electron 做截图式视觉回归；默认尺寸下的最终观感仍应人工确认。
- 本次仅修改前端，因此未运行后端 pytest。
