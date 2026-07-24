# 日志控制台滚动与实时刷新修复：TDD 证据

## 用户旅程

- 自动滚动开启时，程序追加、筛选和布局变化不得取消勾选，并始终停在真实底部。
- 用户主动离开底部时，只暂停对应面板的自动跟随；重新开启后立即回到最新记录。
- 搜索条件变化时，跟随模式回到底部，阅读模式按日志 ID 保留视图锚点。
- 后端每产生一个完整日志行便立即发送并增量插入，不重建整个前后端列表。

## RED / GREEN

| 阶段 | 命令 | 结果 | 证据 |
|---|---|---|---|
| RED | `npm.cmd run test:unit` | FAIL | `immediateSides`、模型增量返回值和 `log-viewport` 模块不存在，测试在预期功能缺口处编译失败。 |
| GREEN | `npm.cmd run test:unit` | PASS | 138/138 项通过。 |
| 边界 RED | `npm.cmd run test:unit` | FAIL | 增量追加尚未同步空状态，新增 UI 合同按预期失败。 |
| 边界 GREEN | `npm.cmd run test:unit` | PASS | 138/138 项通过。 |
| 运行时 RED | Electron 开发模式探针 | FAIL | 非跟随模式筛选后使用页面 `offsetTop`，首条可见记录从 ID 583 错误跳到 ID 606。 |
| 锚点 RED | `npm.cmd run test:unit` | FAIL | 缺少列表内相对坐标换算函数。 |
| 最终 GREEN | `npm.cmd run test:unit` | PASS | 139/139 项通过。 |
| Build | `npm.cmd run build` | PASS | TypeScript、Vite 多页面和 Electron preload 构建成功；仅有既有的大 chunk 提示。 |

## 自动化保证

| 保证 | 测试位置 | 结果 |
|---|---|---|
| 后端日志立即按单记录批次发布，前端仍按100ms批量发布 | `tests/log-core.test.ts` | PASS |
| 模型追加返回新增、去重和环形淘汰的增量 | `tests/log-viewer-model.test.ts` | PASS |
| 程序滚动不会关闭跟随，明确用户滚动离底才关闭 | `tests/log-viewport.test.ts` | PASS |
| 重新启用跟随后清除旧用户滚动意图 | `tests/log-viewport.test.ts` | PASS |
| 筛选后选择相同或最近的日志 ID，并按列表内坐标恢复位置 | `tests/log-viewport.test.ts` | PASS |
| 日志列表可聚焦、使用底部锚点、增量追加并移除高度预估 | `tests/log-console-ui.test.ts` | PASS |

## Electron 开发/生产验收

开发页与构建后的 `logs.html` 结果一致：

- 初始化和清空搜索后自动滚动保持勾选，底部距离为0–1px。
- 代码把 `scrollTop` 设为0时仍保持勾选；下一条后端日志到达后回到底部。
- 模拟滚轮离开底部601px后只取消后端面板的自动滚动。
- 非跟随模式搜索后首条可见记录恢复为ID 600，清空搜索后仍为ID 600。
- 重新勾选后底部距离恢复为1px。
- 单条后端记录追加后旧首行的诊断标记仍存在，证明没有整表重建。

## 已知边界

- 浏览器可能在同一显示帧绘制极短时间内到达的多行日志，但主进程不再等待100ms合并后端记录。
- 项目没有前端 coverage 脚本，因此不报告覆盖率数字。
- 本次未修改 Python 业务代码，没有运行后端 pytest。
- 所有修改保留在工作区，未暂存、未提交。
