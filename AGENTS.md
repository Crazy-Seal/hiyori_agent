# Repository Guidelines

## Project Structure & Module Organization

This is a single-user, local standalone application. Architecture and feature decisions should target local desktop use and must not assume multi-user, distributed, or remote-deployment requirements unless explicitly requested.

The FastAPI backend starts in `main.py`. Application code lives under `app/`: HTTP endpoints are in `routes/`, request and response models in `schemas/`, persistence in `crud/`, orchestration in `services/`, and agent, tool, plugin, and memory implementations in `agent/`. Backend tests are in `tests/`. The Electron/Vite frontend is under `ui/`; renderer code is in `ui/src/`, Electron main-process code in `ui/electron/`, and static Live2D assets in `ui/public/`. Runtime state belongs in `memory/`, not source control. Configuration samples live in `config/` and `.env.sample`.

## Build, Test, and Development Commands

Run the backend in the `ayaya` Conda environment:

```powershell
conda run -n ayaya pip install -r requirements.txt
conda run -n ayaya uvicorn main:app --reload --reload-exclude "agent_workspace/*"
conda run -n ayaya python -B -m pytest tests -q -p no:cacheprovider
```

For the desktop UI, run `npm install` from `ui/`, then use `npm run dev` for Vite and Electron development, `npm run build` for production bundles and TypeScript checks, and `npm run start` to launch the built application.

## Coding Style & Naming Conventions

Use four spaces in Python and two spaces in TypeScript, matching surrounding files. Prefer `snake_case` for Python modules and functions, `PascalCase` for classes and TypeScript types, and `kebab-case.ts` for frontend modules. TypeScript must remain compatible with `strict: true`. Keep modules focused and preserve route/service/DAO boundaries. Write code comments and console or log messages in Chinese where practical.

## Testing Guidelines

Pytest is the backend test framework. Name files `test_<feature>.py` and tests `test_<behavior>`. Add regression coverage for changed behavior; no numeric coverage threshold is configured. `tests/conftest.py` creates a disposable data directory before backend imports. Tests must never access, modify, or delete production storage.

## Environment & Security

Unset `AYAYA_ENV` means production: use repository `memory/`, `config/chat_settings.yaml`, and root `.env`. For explicit production runs, set `AYAYA_ENV=production` and remove `AYAYA_DATA_DIR`. For tests, set `AYAYA_ENV=test` and point `AYAYA_DATA_DIR` outside production `memory/`; all SQLite, checkpoint, Chroma, Mem0/Qdrant, image, and session configuration must remain there. Test mode does not load production `.env`. Before manually starting a test backend, create `$env:AYAYA_DATA_DIR\config\chat_settings.yaml`. Never commit credentials or generated runtime data.

## Commit & Pull Request Guidelines

All commit messages must follow Conventional Commits using `<type>(<scope>): <description>`; the scope is optional. Use concise Chinese imperative descriptions for one logical change, for example `fix(agent): 修复流式工具调用聚合`. Common types include `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, and `chore`. Pull requests should explain purpose, implementation impact, test commands and results, configuration changes, and linked issues. Include screenshots or a short recording for visible UI changes.
