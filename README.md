[**English**](./README.md) | [**简体中文**](./README.zh-CN.md)

# Ayaya

An intelligent desktop pet based on LLM and Agent technologies. It includes a powerful backend based on **FastAPI + LangChain/LangGraph**, and a desktop UI component based on **Electron + Vite + Vue/React/TS** (supporting Live2D).

## Project Structure

The project adopts a decoupled architecture separating frontend and backend:

```
Ayaya/
├── app/                  # FastAPI backend code
│   ├── agent/            # LangGraph Agent
│   ├── config/           # Backend configuration parsing
│   ├── crud/             # Database CRUD layer
│   ├── routes/           # API routing layer
│   ├── schemas/          # Pydantic data models
│   └── services/         # Service layer
├── config/               # Backend configuration files
├── memory/               # Memory storage
├── ui/                   # Frontend source code
│   ├── electron/         # Electron main process and preload scripts
│   ├── public/           # Static resources, Live2D model files, etc.
│   ├── src/              # Frontend page code
│   └── package.json      # Frontend dependencies and script configuration
├── tests/                # Backend automated tests
├── main.py               # FastAPI backend service entry point
└── requirements.txt      # Python environment dependency list
```

## Deployment and Execution

### 1. Backend Deployment (FastAPI)

Python 3.12 is recommended.

1. **Create and activate a virtual environment (miniconda is recommended)**:
   ```powershell
   conda create -n Ayaya python=3.12
   conda activate Ayaya
   ```
2. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
3. **Environment Configuration**:
   Create or update the `.env` file in the project root and fill in your model/search credentials:
   ```dotenv
   # Embedding configuration
   EMBEDDING_API_KEY=YOUR_API_KEY
   EMBEDDING_MODEL=text-embedding-v4
   EMBEDDING_DIMENSION=1024
   EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

   # mem0 memory extraction model (Important: Please use OpenAI models here, otherwise JSON generation errors may occur)
   MEM0_EXTRACTION_MODEL=gpt-5.4
   MEM0_EXTRACTION_BASE_URL=https://www.dmxapi.cn/v1
   MEM0_EXTRACTION_API_KEY=YOUR_API_KEY

   # Coding AI configuration
   CODING_API_KEY=YOUR_API_KEY
   CODING_MODEL=gpt-5.3-codex
   CODING_BASE_URL=https://www.dmxapi.cn/v1
   CODING_TEMPERATURE=0.3

   # Tavily configuration
   TAVILY_API_KEY=YOUR_API_KEY

   # VLM configuration
   VLM_API_KEY=YOUR_API_KEY
   VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   VLM_MODEL=qwen3-vl-plus
   ```
4. **Start the service**:
   ```powershell
   uvicorn main:app --reload --reload-exclude "agent_workspace/*"
   ```
   > The backend will run at http://127.0.0.1:8000 by default.

### Backend environment isolation

Production uses the repository's `memory/` directory and
`config/chat_settings.yaml` by default:

```dotenv
AYAYA_ENV=production
```

Tests must provide a separate data directory. The backend fails fast instead
of falling back to production storage:

```powershell
$env:AYAYA_ENV="test"
$env:AYAYA_DATA_DIR="$env:TEMP\ayaya-test-data"
conda run -n my_agent python -m pytest tests -q
```

In test mode SQLite, checkpoints, Chroma, Mem0/Qdrant, images, and chat
settings stay under `AYAYA_DATA_DIR`, and the production `.env` is not loaded.

### 2. Frontend Deployment (Electron + Vite)

Frontend environment: Node.js 24.9.0

1. **Enter the frontend directory**:
   ```powershell
   cd ui
   ```
2. **Install dependencies**:
   ```powershell
   npm install
   ```
3. **Download Live2D model**
   Go to `https://cubism.live2d.com/sample-data/bin/hiyori_pro/hiyori_pro_zh.zip` to download the default model. Place the downloaded zip file in the `/ui` directory.

4. **Run in development mode**:
   ```powershell
   npm run dev
   ```

## Notes

* **Database**: This project uses local databases to store conversation history and memories. Database files will be automatically generated in the `memory/` directory.
  - SQLite is used for storing chat logs, diaries, summary memories, episodic memory raw text, graph states, etc.
  - Chroma is used for storing long-term episodic memory vectors.
  - mem0 uses Qdrant to store semantic memory raw text and vectors.
* **Live2D Models**: Model assets are placed in the `ui/public/live2d/` directory. You can replace or add new ones in the frontend settings panel according to your needs.
