[**English**](./README.md) | [**简体中文**](./README.zh-CN.md)

# Ayaya

Ayaya 是一个本地 AI 桌宠。它会以 Live2D 角色的形式待在桌面上，可以和你聊天，记住过去的对话，理解你发来的图片，也可以在你允许的情况下使用一些本地工具。

这个项目面向个人桌面使用，不是一个在线托管服务，也不需要用户系统或远程数据库。聊天记录、长期记忆、导入的 Live2D 模型和应用设置都会保存在本机。

## 它能做什么

- 在桌面上显示 Live2D 角色。
- 通过桌面聊天面板和角色对话。
- 流式显示模型回复。
- 保存本地聊天历史和长期记忆。
- 支持发送图片，并用视觉模型生成图片摘要。
- 可按需启用记忆检索、日记检索、联网搜索、读写本地文件、执行 PowerShell 命令和需要确认的截图。
- 在设置窗口里调整模型、提示词、工具、记忆策略、Live2D 模型、位置缩放、视线跟随和动作标签。

## 运行要求

- 主要开发环境是 Windows。
- Python 3.12。
- Conda 环境名为 `ayaya`。
- Node.js 24.x。
- 一个 OpenAI 兼容的聊天模型接口。
- 如果要使用长期记忆、联网搜索或图片理解，需要额外配置对应服务密钥。

## 快速开始

先安装后端依赖：

```powershell
conda run -n ayaya pip install -r requirements.txt
```

然后安装并启动桌面端：

```powershell
cd ui
npm install
npm run dev
```

Electron 会生成临时 API Token，在 `http://127.0.0.1:8000` 启动后端，等待带认证的就绪接口，并在桌面端退出时关闭后端。默认流程不要再单独启动后端。

首次运行前，需要下载默认 Live2D 模型：

```text
https://cubism.live2d.com/sample-data/bin/hiyori_pro/hiyori_pro_zh.zip
```

把 `hiyori_pro_zh.zip` 直接放到 `ui/` 目录下。前端准备脚本会自动解压到 `ui/public/live2d/`，并在需要时下载 Cubism Core。

## 初次配置

打开桌面端的设置窗口，配置以下内容：

- 模型 Base URL、API key、模型名和温度。
- 角色人设和系统提示词。
- 启用哪些工具。
- 记忆和上下文策略。
- Live2D 模型、位置、缩放、视线跟随和动作标签。

正常本地使用时，聊天模型配置保存在 `config/chat_settings.yaml`。

部分可选功能还需要在项目根目录 `.env` 中配置密钥：

```dotenv
# 长期记忆 embedding
EMBEDDING_API_KEY=YOUR_API_KEY
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 长期记忆提取（此处请选择OpenAI的模型，否则可能出现json生成错误）
MEM0_EXTRACTION_MODEL=gpt-5.4
MEM0_EXTRACTION_BASE_URL=https://www.dmxapi.cn/v1
MEM0_EXTRACTION_API_KEY=YOUR_API_KEY

# 联网搜索
TAVILY_API_KEY=YOUR_API_KEY

# 屏幕点击和图片理解
VLM_API_KEY=YOUR_API_KEY
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL=qwen3-vl-plus
```

如果只想先体验基础聊天，优先在设置窗口里配好聊天模型即可。其他密钥只需要在使用对应功能时再补。

## 开发说明

后端是一个 FastAPI 应用，入口在 `main.py`。主要代码位于 `app/`：

- `app/routes/` HTTP 和流式接口。
- `app/services/` 负责聊天、设置和历史记录等应用服务。
- `app/agent/` Agent 运行时、工具、记忆、模型客户端和执行管道。
- `app/crud/` 负责本地持久化访问。
- `app/schemas/` Pydantic 数据模型。

桌面端位于 `ui/`：

- `ui/electron/` Electron 主进程和 preload 代码。
- `ui/src/` 桌宠、聊天、设置、Live2D 和图片处理等渲染进程代码。
- `ui/public/` 前端静态资源。
- `ui/user_data/` 保存运行时导入的模型和前端设置。

## 构建与启动

前端开发模式：

```powershell
cd ui
npm run dev
```

前端生产构建：

```powershell
cd ui
npm run build
npm run start
```

`npm run dev` 和 `npm run start` 默认都由 Electron 管理带认证的后端。Electron
通过 Conda 的 JSON 环境列表查找名为 `ayaya` 的环境，然后直接启动该环境的
Python；长期运行的后端进程树不再包含 `conda run`。

如需独立调试后端，两个终端必须使用同一个临时 Token。不要持久化或提交该 Token：

```powershell
# 终端 1
$env:AYAYA_API_TOKEN="<至少43字符的临时Base64URL Token>"
conda run -n ayaya python -B -m app.server

# 终端 2
$env:AYAYA_API_TOKEN="<同一个临时Token>"
$env:AYAYA_MANAGE_BACKEND="false"
cd ui
npm run dev
```

以下环境变量可用于开发覆盖：

- `AYAYA_PYTHON_EXECUTABLE`：指定 Python 可执行文件，替代默认的 `ayaya` Conda 环境自动发现。
- `AYAYA_BACKEND_CWD`：修改 Electron 启动后端时使用的工作目录。
- `AYAYA_BACKEND_BASE_URL`：让 Electron 连接其他回环地址上的后端；外部后端模式仍必须提供匹配的 `AYAYA_API_TOKEN`。

## 测试

后端测试必须使用隔离的数据目录：

```powershell
$env:AYAYA_ENV="test"
$env:AYAYA_DATA_DIR="$env:TEMP\ayaya-test-data"
conda run -n ayaya python -B -m pytest tests -q -p no:cacheprovider
```

前端检查：

```powershell
cd ui
npm run typecheck
npm run test:unit
```

## 本地数据

正常本地运行会使用：

- `memory/` 保存后端运行数据、聊天历史、checkpoint、图片和记忆数据。
- `config/chat_settings.yaml` 保存聊天会话配置。
- `ui/user_data/` 保存导入的 Live2D 模型、模型元数据、前端设置和模型变换数据。

不要提交凭据或生成的运行数据。
