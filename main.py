import os
import json
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# === 记忆与数据库相关导入 ===
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

DB_URL = os.getenv("DATABASE_URL")

pool = None
checkpointer = None

if DB_URL:
    pool = ConnectionPool(conninfo=DB_URL, max_size=20, kwargs={"autocommit": True})
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()

SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手。你的回答应该：
- 简洁但友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
"""

# 🚀 修复 1：使用 alias 兼容前端的驼峰命名
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")

class Message(BaseModel):
    role: str
    content: str

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

# 🚀 修复 2：在启动时确保 chat_history 表被正确创建
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Agent 启动中...")
    if pool:
        try:
            # 从连接池中取出一个具体连接 (conn) 给建表函数用
            with pool.connection() as conn:
                PostgresChatMessageHistory.create_tables(conn, "chat_history")
            print("✅ Supabase chat_history 表就绪！")
        except Exception as e:
            print(f"⚠️ 检查/创建 chat_history 表时出现提示 (通常是因为表已存在): {e}")
            
    yield
    print("👋 Agent 已关闭")
    if pool:
        pool.close()

app = FastAPI(
    title="Personal Agent API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent_graph = create_agent_graph()

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "0.1.0",
        "agent": "ready",
        "database": "connected" if pool else "disconnected"
    }

@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
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
            
            if pool:
                history = PostgresChatMessageHistory(
                    "chat_history",
                    session_id,
                    sync_connection=pool
                )
                past_messages = history.messages 
            
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + past_messages + [user_message]
            
            async for chunk in llm_service.model.astream(messages):
                content = chunk.content or ""
                full_response += content
                yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                await asyncio.sleep(0.01)
            
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