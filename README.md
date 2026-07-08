[**English**](./README.md) | [**简体中文**](./README.zh-CN.md)

# Ayaya

Ayaya is a local AI desktop pet. It lives on your desktop as a Live2D character, chats with you through an LLM, remembers past conversations, can look at images you send, and can use a small set of local tools when you enable them.

The app is built for personal desktop use. It is not a hosted service, and it does not need a user system or a remote database. Your conversations, memories, imported Live2D models, and app settings are stored locally.

## What It Does

- Shows a Live2D character on the desktop.
- Lets you chat with the character in a desktop chat panel.
- Streams replies as they are generated.
- Saves local chat history and long-term memory.
- Supports image messages and vision-model image summaries.
- Can search memories, search diaries, browse the web, read or edit local files, run PowerShell commands, and request a screenshot with your confirmation.
- Lets you configure the model, prompt, tools, memory behavior, Live2D model, model position, cursor tracking, and motion labels from the settings window.

## Requirements

- Windows is the primary development environment.
- Python 3.12.
- Conda environment named `my_agent`.
- Node.js 24.x.
- An OpenAI-compatible chat model endpoint.
- Optional service keys for memory embedding, web search, and vision features.

## Quick Start

Start the backend first:

```powershell
conda run -n my_agent pip install -r requirements.txt
conda run -n my_agent uvicorn main:app --reload --reload-exclude "agent_workspace/*"
```

The backend runs at `http://127.0.0.1:8000`.

Then prepare and start the desktop app:

```powershell
cd ui
npm install
npm run dev
```

Before the first frontend run, download the default Live2D model:

```text
https://cubism.live2d.com/sample-data/bin/hiyori_pro/hiyori_pro_zh.zip
```

Put `hiyori_pro_zh.zip` directly inside `ui/`. The frontend preparation script will extract it into `ui/public/live2d/` and download Cubism Core if needed.

## First Setup

Open the settings window in the desktop app and configure:

- Model base URL, API key, model name, and temperature.
- Character profile and system prompt.
- Enabled tools.
- Memory and context behavior.
- Live2D model, position, scale, cursor tracking, and motion labels.

Chat model settings are saved in `config/chat_settings.yaml` in normal local use.

Some optional features also need keys in the root `.env` file:

```dotenv
# Long-term memory embeddings
EMBEDDING_API_KEY=YOUR_API_KEY
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Long-term memory extraction (Please use OpenAI models here, otherwise JSON generation errors may occur)
MEM0_EXTRACTION_MODEL=gpt-5.4
MEM0_EXTRACTION_BASE_URL=https://www.dmxapi.cn/v1
MEM0_EXTRACTION_API_KEY=YOUR_API_KEY

# Web search
TAVILY_API_KEY=YOUR_API_KEY

# Image and screenshot understanding
VLM_API_KEY=YOUR_API_KEY
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL=qwen3-vl-plus
```

If you only want basic chat, configure the chat model in the settings window first. Add the optional keys only for the features you plan to use.

## Development Notes

The backend is a FastAPI app in `main.py`. Most backend code is under `app/`:

- `app/routes/` contains HTTP and streaming API routes.
- `app/services/` coordinates chat, settings, and history services.
- `app/agent/` contains the agent runtime, tools, memory, model clients, and execution pipeline.
- `app/crud/` handles local persistence.
- `app/schemas/` contains Pydantic models.

The desktop app is under `ui/`:

- `ui/electron/` contains Electron main-process and preload code.
- `ui/src/` contains renderer code for the pet, chat, settings, Live2D, and image handling.
- `ui/public/` contains static frontend assets.
- `ui/user_data/` stores imported models and frontend settings at runtime.

## Build

Backend:

```powershell
conda run -n my_agent uvicorn main:app --reload --reload-exclude "agent_workspace/*"
```

Frontend development:

```powershell
cd ui
npm run dev
```

Frontend production build:

```powershell
cd ui
npm run build
npm run start
```

If the backend is not running on `http://127.0.0.1:8000`, set `BACKEND_BASE_URL` before starting Electron.

## Tests

Backend tests must use isolated test storage:

```powershell
$env:AYAYA_ENV="test"
$env:AYAYA_DATA_DIR="$env:TEMP\ayaya-test-data"
conda run -n my_agent python -B -m pytest tests -q -p no:cacheprovider
```

Frontend checks:

```powershell
cd ui
npm run typecheck
npm run test:unit
```

## Local Data

Normal local runs use:

- `memory/` for backend runtime data, chat history, checkpoints, images, and memory stores.
- `config/chat_settings.yaml` for chat session settings.
- `ui/user_data/` for imported Live2D models, model metadata, frontend settings, and model transform data.

Do not commit credentials or generated runtime data.
