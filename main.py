import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from app.runtime import get_images_dir, is_test_environment

# 测试环境不得从生产 .env 文件继承凭据。
if not is_test_environment():
    load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from app.agent.core.state_manager import StateManager
from app.security.local_api import install_local_api_security, load_api_token

from app.routes.agent import router as agent_router
from app.routes.chat_settings import router as chat_settings_router
from app.routes.chat_history import router as memory_router
from app.routes.control_screen import router as control_screen_router
from app.routes.screenshot import router as screenshot_router
from app.routes.tools import router as tools_router
from app.routes.plugins import router as plugins_router

# 控制台日志基础配置：让 Agent 的收发日志在本地启动时可见
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """在任何 DAO 或记忆组件访问前完成统一存储初始化和迁移。"""
    manager = StateManager("__storage_init__")
    try:
        await manager._get_db()
    finally:
        await manager.close()
    yield


# FastAPI 应用入口：仅负责启动和挂载路由
app = FastAPI(title="Ayaya server", version="0.1.0", lifespan=lifespan)
install_local_api_security(app, load_api_token())
# 挂载 Agent 相关 API
app.include_router(agent_router)
app.include_router(chat_settings_router)
app.include_router(memory_router)
app.include_router(control_screen_router)
app.include_router(screenshot_router)
app.include_router(tools_router)
app.include_router(plugins_router)

# 静态文件服务：用于访问保存的图片
IMAGES_DIR = get_images_dir()
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/")
async def root():
    # 根路径用于快速确认服务是否启动
    return {"message": "Ayaya server is running"}


@app.get("/internal/ready")
async def internal_ready():
    """返回仅供 Electron 主进程使用的后端就绪状态。"""
    return {"ready": True}


@app.post("/internal/shutdown")
async def internal_shutdown(request: Request):
    """请求当前 Uvicorn 实例执行优雅关闭。"""
    server = getattr(request.app.state, "uvicorn_server", None)
    if server is None:
        raise HTTPException(status_code=503, detail="后端不由受控启动器管理")
    server.should_exit = True
    return {"shutting_down": True}


if __name__ == "__main__":
    from app.server import run

    run()
