import os
import json
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# === 记忆与数据库相关导入 (新增) ===
from psycopg_pool import ConnectionPool
from langchain_postgres import PostgresChatMessageHistory
from langgraph.checkpoint.postgres import PostgresSaver

# 导入你自己的模块
from graph.state import AgentState
from graph.nodes import call_model, should_continue
from services.llm import llm_service
from graph.builder import create_agent_graph

# 加载环境变量
load_dotenv()

# === 数据库连接池初始化 ===
# 务必确保你的环境变量中 DATABASE_URL 是 6543 端口的 Transaction mode 链接
DB_URL = os.getenv("DATABASE_URL")

pool = None
checkpointer = None

if DB_URL:
    # 建立连接池，max_size=20 足够个人日常使用且不会撑爆免费额度
    pool = ConnectionPool(conninfo=DB_URL, max_size=20, kwargs={"autocommit": True})
    
    # 顺手为 LangGraph 创建一个数据库守护者
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()  # 启动时自动去 Supabase 建表（如果表不存在的话）

# 系统提示词
SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手。你的回答应该：
- 简洁但友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
"""

# 请求模型
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

class Message(BaseModel):
    role: str
    content: str

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Agent 启动中...")
    yield
    print("👋 Agent 已关闭")
    # 优雅地关闭数据库连接
    if pool:
        pool.close()

# === 统一创建 FastAPI 应用 ===
app = FastAPI(
    title="Personal Agent API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan
)

# === CORS 配置 ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建 Agent Graph 单例
# 提示：如果你希望 /api/v1/chat 里的 LangGraph 也拥有记忆，
# 建议你去 builder.py 里让 create_agent_graph 接收 checkpointer 参数，
# 例如：agent_graph = create_agent_graph(checkpointer=checkpointer)
agent_graph = create_agent_graph()

@app.get("/api/v1/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "agent": "ready",
        "database": "connected" if pool else "disconnected"
    }

@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """非流式对话接口（用于测试）"""
    try:
        message = HumanMessage(content=request.message)
        config = {
            "configurable": {
                "thread_id": request.conversation_id or "default"
            }
        }
        
        result = await agent_graph.ainvoke(
            {"messages": [message]},
            config
        )
        
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        response_content = ai_messages[-1].content if ai_messages else "抱歉，我没有生成回复。"
        
        return {
            "success": True,
            "response": response_content,
            "conversation_id": request.conversation_id or "default"
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 + Supabase 记忆持久化 (核心修改区)"""
    try:
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        user_message = HumanMessage(content=request.message)
        session_id = request.conversation_id or "default"
        
        config = {
            "configurable": {
                "thread_id": session_id
            }
        }
        
        async def generate():
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': session_id})}\n\n"
            
            full_response = ""
            past_messages = []
            history = None
            
            # --- 1. 从 Supabase 读取记忆 ---
            if pool:
                history = PostgresChatMessageHistory(
                    table_name="chat_history", # 在 Supabase 中创建的表名
                    session_id=session_id,     # 根据前端传来的 ID 找对应记忆
                    sync_connection=pool
                )
                past_messages = history.messages # 取出所有历史对话
            
            # --- 2. 组合对话上下文 ---
            # 顺序很重要：人设 -> 过去的聊天记录 -> 用户最新说的话
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + past_messages + [user_message]
            
            # --- 3. 流式输出 ---
            async for chunk in llm_service.model.astream(messages):
                content = chunk.content or ""
                full_response += content
                yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                await asyncio.sleep(0.01) # 稍微缩短睡眠时间，打字更顺滑
            
            # --- 4. 存入新记忆 ---
            # 等 AI 全部说完后，把这一回合的对话写入 Supabase
            if history:
                history.add_user_message(request.message)
                history.add_ai_message(full_response)
            
            yield f"data: {json.dumps({'type': 'end', 'fullResponse': full_response})}\n\n"
            
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        
    except Exception as e:
        error_data = {
            "type": "error",
            "message": str(e),
            "conversation_id": request.conversation_id or "default"
        }
        return StreamingResponse(
            [f"data: {json.dumps(error_data)}\n\n"],
            media_type="text/event-stream",
            status_code=500
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)