# 设置页与日志页视觉系统统一：TDD 证据

## Source plan

本次用户旅程和验收标准来自当前任务中批准的《Ayaya 设置页与日志页视觉系统统一》实施计划。

## User journeys

- 作为用户，我希望设置面板与日志控制台中的同类控件具有一致的视觉和交互反馈，以便快速判断操作语义。
- 作为维护者，我希望页面通过共享组件类组合界面，以便后续修改不会再次产生多套按钮、复选框和表单样式。
- 作为键盘或减少动态效果的用户，我希望所有共享控件具备统一的焦点、禁用和 reduced-motion 状态。

## Task report

| 阶段 | 命令 | 结果 | 证据 |
|---|---|---|---|
| RED | `npm.cmd run test:unit` | FAIL | 原有 122 项通过；新增 4 项因 `window-components.css` 不存在、静态及动态控件尚未使用共享类而失败。 |
| GREEN | `npm.cmd run test:unit` | PASS | 126/126 项通过；共享样式层、语义控件、交互状态和动态控件映射合同全部通过。 |
| Build | `npm.cmd run build` | PASS | TypeScript、Vite 多页面构建及 Electron preload 构建成功，产物包含 `index.html`、`settings.html` 和 `logs.html`。 |

## Test specification

| # | 保证内容 | 测试 | 类型 | 结果 |
|---|---|---|---|---|
| 1 | 设置页和日志页共同引用统一组件样式层 | `tests/window-components.test.ts` | 静态合同 | PASS |
| 2 | 按钮、表单、复选框、滑块、表面、表格、弹窗和反馈类均存在 | `tests/window-components.test.ts` | 静态合同 | PASS |
| 3 | 共享控件包含 hover、active、focus、disabled 和 reduced-motion 状态 | `tests/window-components.test.ts` | 静态合同 | PASS |
| 4 | 两个窗口的静态控件使用正确语义和尺寸类 | `tests/window-components.test.ts` | 静态合同 | PASS |
| 5 | 模型、表情、插件、工具和 MCP 动态控件使用共享类 | `tests/window-components.test.ts` | 静态合同 | PASS |
| 6 | 确认框在危险和警告语义之间正确切换共享按钮类 | `tests/confirm-dialog.test.ts` | 单元测试 | PASS |

## Coverage and known gaps

- 项目没有配置前端 coverage 脚本，CSS 也无法由当前 Node 测试运行器计算语句覆盖率，因此没有可报告的百分比。
- 合同测试覆盖全部新增共享类及静态、动态使用入口；现有完整前端单元测试全部通过。
- 本机没有配置窗口截图或 Playwright 视觉回归设施。颜色观感、最小窗口换行和真实鼠标按压效果仍需通过 `npm run dev` 与 `npm run start` 人工验收。
- 本次未修改 Python 业务代码，未运行后端 pytest。
