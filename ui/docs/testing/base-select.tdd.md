# 原生可定制下拉框升级：TDD 证据

## 用户旅程

- 作为用户，我希望设置面板和日志控制台的下拉框具有一致的暖色深色样式，并能清楚看到展开箭头、当前选项和悬停状态。
- 作为键盘用户，我希望继续使用方向键、Enter、Escape 和 Tab 操作原生下拉框。
- 作为打包应用用户，我希望 `loadFile()` 加载的页面与开发模式使用相同的共享 CSS 和资源。

## RED / GREEN

| 阶段 | 命令 | 结果 | 证据 |
|---|---|---|---|
| RED | `npm.cmd run test:unit` | FAIL | 132 项中 129 项通过；新增的 `base-select` 样式合同、动态表情下拉框可访问名称和 Vite 相对资源基址 3 项按预期失败。 |
| GREEN | `npm.cmd run test:unit` | PASS | 132/132 项通过。 |
| Build | `npm.cmd run build` | PASS | TypeScript、Vite 多页面构建和 Electron preload 构建成功；仅保留既有的大 chunk 提示。 |

## 自动化合同

| 保证 | 测试位置 | 结果 |
|---|---|---|
| 回退 SVG 保留在 `@supports` 外，支持环境中移除背景图 | `tests/window-components.test.ts` | PASS |
| Select 与 Picker 同时启用 `appearance: base-select` | `tests/window-components.test.ts` | PASS |
| Picker、箭头、打开状态、选项 hover/focus/checked/disabled 和 checkmark 样式存在 | `tests/window-components.test.ts` | PASS |
| 通用只读规则不会命中 Select | `tests/window-components.test.ts` | PASS |
| 动态表情 Select 具有包含动作名称的 `aria-label` | `tests/window-components.test.ts` | PASS |
| Vite 生产构建使用相对资源路径 | `tests/window-components.test.ts` | PASS |

## Electron 38 运行时验收

分别加载 Vite 开发页和 `dist` 生产页，结果一致：

- `CSS.supports("appearance", "base-select")` 为 `true`。
- Select 与 Picker 的计算样式 `appearance` 均为 `base-select`。
- 日志页紧凑 Select 高度为 32px，设置页标准 Select 高度为 40px。
- 支持环境中的回退背景图为 `none`；Picker 箭头为橙色。
- Picker 背景为暖色深色表面、圆角 14px、最大高度 320px；选项字号 13px、高度 32px。
- 鼠标可打开 Picker，Escape 可关闭，Tab 可移动到下一个 Select。
- 展开后按向下键可从 `debug` 选择 `info`，Enter 确认后关闭 Picker。
- 开发和生产截图中的箭头、Picker 背景、选中标记和选项状态一致。

## 边界

- 项目没有前端 coverage 脚本，因此不报告覆盖率数字。
- 本次仅修改前端共享样式、可访问名称和构建资源基址，没有运行后端 pytest。
- 所有修改保留在工作区，未暂存、未提交。
