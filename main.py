import logging
import os

from dotenv import load_dotenv

from app.runtime import get_images_dir, is_test_environment

# 测试环境不得从生产 .env 文件继承凭据。
if not is_test_environment():
    load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.agent import router as agent_router
from app.routes.chat_settings import router as chat_settings_router
from app.routes.chat_history import router as memory_router
from app.routes.screenshot import router as screenshot_router
from app.routes.tools import router as tools_router
from app.routes.plugins import router as plugins_router

# 控制台日志基础配置：让 Agent 的收发日志在本地启动时可见
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# FastAPI 应用入口：仅负责启动和挂载路由
app = FastAPI(title="Ayaya server", version="0.1.0")
# 挂载 Agent 相关 API
app.include_router(agent_router)
app.include_router(chat_settings_router)
app.include_router(memory_router)
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


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_excludes=["agent_workspace/*"]
    )
