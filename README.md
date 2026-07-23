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
- Conda environment named `ayaya`.
- Node.js 24.x.
- An OpenAI-compatible chat model endpoint.
- Optional service keys for memory embedding, web search, and vision features.

## Quick Start

Install the backend dependencies:

```powershell
conda run -n ayaya pip install -r requirements.txt
```

Then install and start the desktop app:

```powershell
cd ui
npm install
npm run dev
```

Electron generates a temporary API token, starts the backend on
`http://127.0.0.1:8000`, waits for its authenticated readiness endpoint, and
shuts it down when the desktop app exits. Do not start a separate backend for
the default workflow.

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

Both `npm run dev` and `npm run start` let Electron manage the authenticated
backend by default. Electron discovers the `ayaya` Conda environment through
Conda's JSON environment list, then starts that environment's Python executable
directly; `conda run` is not kept in the long-running backend process tree.

For standalone backend development, use the same temporary token in both
terminals. Do not persist or commit this token:

```powershell
# Terminal 1
$env:AYAYA_API_TOKEN="<temporary Base64URL token with at least 43 characters>"
conda run -n ayaya python -B -m app.server

# Terminal 2
$env:AYAYA_API_TOKEN="<the same temporary token>"
$env:AYAYA_MANAGE_BACKEND="false"
cd ui
npm run dev
```

The following environment variables are development overrides:

- `AYAYA_PYTHON_EXECUTABLE`: use a specific Python executable instead of automatically discovering the Conda environment named `ayaya`.
- `AYAYA_BACKEND_CWD`: change the working directory used when Electron starts the backend.
- `AYAYA_BACKEND_BASE_URL`: connect Electron to a different loopback backend address; external mode still requires the matching `AYAYA_API_TOKEN`.

## Tests

Backend tests must use isolated test storage:

```powershell
$env:AYAYA_ENV="test"
$env:AYAYA_DATA_DIR="$env:TEMP\ayaya-test-data"
conda run -n ayaya python -B -m pytest tests -q -p no:cacheprovider
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
