﻿[**English**](./README.md) | [**简体中文**](./README.zh-CN.md)

# Ayaya

基于LLM和Agent技术的智能桌宠。包含一个基于 **FastAPI + LangChain/LangGraph** 的后端，以及一个基于 **Electron + Vite + Vue/React/TS** 的Live2D桌面端 UI。

##  项目结构

项目采用前后端分离的架构：

```
Ayaya/
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

### 1. 后端部署 (FastAPI)

建议使用 Python 3.12。

1. **创建并激活虚拟环境 (推荐使用miniconda)**:
   ```powershell
   conda create -n Ayaya python=3.12
   conda activate Ayaya
   ```
2. **安装依赖**:
   ```powershell
   pip install -r requirements.txt
   ```
3. **环境配置**:
   在项目根目录创建或修改 `.env` 文件，并填写相关密钥：
   ```dotenv
   # embedding配置
   EMBEDDING_API_KEY=YOUR_API_KEY
   EMBEDDING_MODEL=text-embedding-v4
   EMBEDDING_DIMENSION=1024
   EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   
   # mem0记忆提取模型（重要：此处请选择OpenAI的模型，否则可能出现json生成错误）
   MEM0_EXTRACTION_MODEL=gpt-5.4
   MEM0_EXTRACTION_BASE_URL=https://www.dmxapi.cn/v1
   MEM0_EXTRACTION_API_KEY=YOUR_API_KEY
   
   # 编程AI配置
   CODING_API_KEY=YOUR_API_KEY
   CODING_MODEL=gpt-5.3-codex
   CODING_BASE_URL=https://www.dmxapi.cn/v1
   CODING_TEMPERATURE=0.3
   
   # Tavily配置
   TAVILY_API_KEY=YOUR_API_KEY
   
   # VLM配置
   VLM_API_KEY=YOUR_API_KEY
   VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   VLM_MODEL=qwen3-vl-plus
   ```
4. **启动服务**:
   ```powershell
   uvicorn main:app --reload --reload-exclude "agent_workspace/*"
   ```
   > 默认后端将在 http://127.0.0.1:8000 运行。

### 后端运行环境隔离

生产环境默认使用项目下的 `memory/` 和 `config/chat_settings.yaml`：

```dotenv
AYAYA_ENV=production
```

测试环境必须显式提供独立数据目录，否则后端会直接拒绝启动或创建存储：

```powershell
$env:AYAYA_ENV="test"
$env:AYAYA_DATA_DIR="$env:TEMP\ayaya-test-data"
conda run -n my_agent python -m pytest tests -q
```

测试模式下 SQLite、checkpoint、Chroma、Mem0/Qdrant、图片和会话配置均位于
`AYAYA_DATA_DIR` 内，并且不会加载生产 `.env`。

### 2. 前端部署 (Electron + Vite)

环境： Node.js 24.9.0

1. **进入前端目录**:
   ```powershell
   cd ui
   ```
2. **安装依赖**:
   ```powershell
   npm install
   ```
3. **下载live2d模型**
   进入`https://cubism.live2d.com/sample-data/bin/hiyori_pro/hiyori_pro_zh.zip`
下载默认模型，将下载后的压缩包放在/ui路径下


4. **开发模式运行**:
   ```powershell
   npm run dev
   ```

##  备注

* **数据库**: 本项目使用本地数据库存储对话历史和记忆，数据库文件会自动生成于 memory/ 目录中。
  - sqlite 用于存储聊天记录、日记、摘要记忆、情景记忆原文、图状态等；
  - chroma 用于存储长期情景记忆向量；
  - mem0使用 Qdrant 存储语义记忆原文和向量。
* **Live2D 模型**: 模型资产放在 ui/public/live2d/ 目录下，可以在前端的设置面板进行替换或新增。
