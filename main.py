import logging

import uvicorn
from fastapi import FastAPI

from app.routes.agent import router as agent_router
from app.routes.chat_settings import router as chat_settings_router
from app.routes.memory import router as memory_router

# 控制台日志基础配置：让 Agent 的收发日志在本地启动时可见
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# FastAPI 应用入口：仅负责启动和挂载路由
app = FastAPI(title="Hiyori Agent", version="0.1.0")
# 挂载 Agent 相关 API
app.include_router(agent_router)
app.include_router(chat_settings_router)
app.include_router(memory_router)


@app.get("/")
async def root():
    # 根路径用于快速确认服务是否启动
    return {"message": "Hiyori Agent is running"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["agent_workspace/*"]
    )