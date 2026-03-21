import os
import sys
import asyncio
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from services.database import db_service
from graph.builder import create_agent_graph
from api.routers import chat

# 定义响应格式防止中文乱码现象
class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """全局应用生命周期：管理数据库与依赖注入"""
    
    print("🚀 Kiki Agent Module Server 启动中...")
    
    # 建立数据库连接及 Checkpointer 实例
    await db_service.connect()
    
    # 构建并编译 LangGraph，注入至 FastAPI 的全局 state 供路由器调用
    app.state.agent_graph = create_agent_graph(db_service.checkpointer)
    
    yield  # 服务运行期
    
    print("👋 Kiki Agent Module Server 已关闭")
    # 清理数据库连接池等资源
    await db_service.disconnect()

# 初始化应用实例 (极简主干架构)
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan
)

# 挂载 CORS 凭证安全配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 装载全系统的 Router
app.include_router(chat.router)

if __name__ == "__main__":
    import uvicorn  
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)