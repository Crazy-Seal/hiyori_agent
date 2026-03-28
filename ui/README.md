# UI (Electron + TypeScript)

桌宠前端位于 `ui/`，功能包括：
- 使用 Electron 创建透明无边框置顶窗口
- 窗口固定在桌面右下角
- 渲染 Live2D 角色（来自 `hiyori_pro_zh.zip`）
- 角色下方输入框，向后端 `POST /chat` 发送消息
- 模型视线跟随鼠标移动
- 透明区域鼠标点击穿透（保留气泡/输入框/模型交互）
- 在模型区域滚轮缩放，双击重置比例

模型管理说明：
- 在设置窗口的“模型管理”中支持导入 Live2D 模型文件夹。
- 导入后模型会被移动到 `ui/dist/live2d/{模型名}`。
- 模型与 `session_id` 映射会持久化在 `ui/user_data/models.json`。
- 删除模型时会同步删除 `ui/dist/live2d/{模型名}` 目录和持久化记录。
- 默认内置模型不可删除。

说明：首次执行 `npm run dev` 或 `npm run build` 会自动下载 `live2dcubismcore.min.js` 到 `public/`，并自动解压模型资源。

## 安装

```powershell
cd ui
npm install
```

## 开发模式

```powershell
npm run dev
```

默认请求后端地址：`http://127.0.0.1:8000/chat`

可通过环境变量修改：

```powershell
$env:BACKEND_BASE_URL="http://127.0.0.1:8000"
npm run dev
```

## 打包前构建

```powershell
npm run build
```

## 运行构建产物

```powershell
npm run start
```
