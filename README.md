# Hiyori Agent

基于LLM和Agent技术的智能桌宠。它包含一个基于 **FastAPI + LangChain/LangGraph** 的后端，以及一个基于 **Electron + Vite + Vue/React/TS** (支持 Live2D) 的桌面端 UI。

##  项目结构

项目采用前后端分离的架构：

```
hiyori_agent/
├── app/                  # FastAPI 后端代码
│   ├── agent/            # LangGraph Agent
│   ├── config/           # 后端配置文件解析
│   ├── crud/             # 数据库 CRUD 层
│   ├── routes/           # API 路由层
│   ├── schemas/          # Pydantic 数据模型
│   └── services/         # 服务层
├── config/               # 后端配置文件
├── memory/               # 记忆存储
├── ui/                   # 前端源码
│   ├── electron/         # Electron 主进程及预加载脚本
│   ├── public/           # 静态资源，Live2D 模型文件等
│   ├── src/              # 前端页面代码
│   └── package.json      # 前端依赖与脚本配置
├── tests/                # 后端自动化测试
├── main.py               # FastAPI 后端服务启动入口
└── requirements.txt      # Python 环境依赖清单
```

##  部署与运行方法

要完整运行本项目，需要分别启动后端 API 服务和前端客户端。

### 1. 后端部署 (FastAPI)

后端依赖 Python 环境，建议使用 Python 3.12。

1. **创建并激活虚拟环境 (推荐)**:
   `python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   `
1. **安装依赖**:
   `pip install -r requirements.txt
   `
2. **环境配置**:
   修改或确认 config/settings.yaml 配置，填入您使用的大模型 API key ，或将 API key 填入环境变量中
3. **启动服务**:
   `uvicorn main:app --reload --reload-exclude agent_workspace/*
   `
   > 默认后端将在 http://127.0.0.1:8000 运行。

### 2. 前端部署 (Electron + Vite)

前端环境： Node.js 24.9.0

1. **进入前端目录**:
   `powershell
   cd ui
   `
2. **安装依赖**:
   `npm install
   # 或使用 pnpm install / yarn install
   `
3. **开发模式运行**:
   `npm run dev
   `
   > 启动 Vite 开发服务器并拉起 Electron 客户端窗口，展示 Live2D 桌宠并与后端交互。

##  备注

* **数据库**: 本项目使用本地 SQLite 进行对话历史和运行状态的记忆暂存，数据库文件会自动生成于 memory/sqlite/ 目录中。
* **Live2D 模型**: 模型资产放在 ui/public/live2d/ 目录下，您可以根据需要，在前端的设置面板进行替换或新增。
