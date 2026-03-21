import os
import json
import asyncio
import uuid
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# 1. 👈 替换为全异步的驱动
from psycopg_pool import AsyncConnectionPool 
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from graph.state import AgentState
from graph.nodes import call_model, should_continue
from services.llm import llm_service
from graph.builder import create_agent_graph

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
print(f"🛑 检查一下读到的 DB_URL 是: {DB_URL}")

# 先声明为全局变量，等待 FastAPI 启动后再注入灵魂
pool = None
checkpointer = None
agent_graph = None 

SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手。你的回答应该：
- 简洁但友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
"""

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")

class Message(BaseModel):
    role: str
    content: str

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

def ensure_uuid(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))

# 2. 👈 核心重构：在生命周期内初始化异步数据库
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, checkpointer, agent_graph
    print("🚀 Agent 启动中...")
    
    if DB_URL:
        try:
            pool = AsyncConnectionPool(
                conninfo=DB_URL, 
                max_size=20, 
                kwargs={
                    "autocommit": True, 
                    "prepare_threshold": None
                }
            )
            checkpointer = AsyncPostgresSaver(pool)
            
            # 👈 修正这里：去掉 asetup 的 'a'，改为 setup
            await checkpointer.setup() 
            
            agent_graph = create_agent_graph(checkpointer)
            print("✅ 成功启动：Supabase 全异步持久化模式！")
        except Exception as e:
            print(f"❌ 数据库连接失败，切换到内存模式: {e}")
            agent_graph = create_agent_graph(None)
    else:
        agent_graph = create_agent_graph(None)
        print("⚠️ 运行模式：仅内存存储")
        
    yield
    
    print("👋 Agent 已关闭")
    if pool:
        await pool.close()

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
        original_session_id = request.conversation_id or "default"
        db_session_id = ensure_uuid(original_session_id)
        
        config = {
            "configurable": {
                "thread_id": db_session_id
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
            "conversation_id": original_session_id
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    try:
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        original_session_id = request.conversation_id or "default"
        db_session_id = ensure_uuid(original_session_id)
        
        user_message = HumanMessage(content=request.message)
        
        config = {
            "configurable": {
                "thread_id": db_session_id
            }
        }

        async def generate():
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': original_session_id}, ensure_ascii=False)}\n\n"
            
            full_response = ""
            
            try:
                async for event in agent_graph.astream_events(
                    {"messages": [user_message]},
                    config=config,
                    version="v2"
                ):
                    kind = event["event"]
                    name = event["name"]
                    
                    if kind == "on_chain_start" and name == "call_model":
                        yield f"data: {json.dumps({'type': 'event', 'status': 'thinking', 'message': 'Kiki 正在思考...'}, ensure_ascii=False)}\n\n"
                    
                    elif kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            full_response += chunk.content
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                            
                    elif kind == "on_tool_start":
                        tool_input = event["data"].get("input", "")
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'tool_input': tool_input, 'status': 'running'}, ensure_ascii=False)}\n\n"
                        
                    elif kind == "on_tool_end":
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'status': 'completed'}, ensure_ascii=False)}\n\n"

                # 3. 👈 注意这里：异步环境里放心用 aget_state 获取快照
                print(f"--- 尝试检查 thread_id: {db_session_id} 的状态 ---")
                snapshot = await agent_graph.aget_state(config) 
                if snapshot and snapshot.values:
                    print(f"--- 数据库中最新持久化消息数: {len(snapshot.values.get('messages', []))} ---")
                else:
                    print("--- 当前 thread_id 下无任何状态记录 ---")       

            except Exception as stream_e:
                error_data = {
                    "type": "error",
                    "message": str(stream_e),
                    "conversation_id": original_session_id
                }
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                return

            yield f"data: {json.dumps({'type': 'end', 'fullResponse': full_response}, ensure_ascii=False)}\n\n"
          
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
            [f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"],
            media_type="text/event-stream",
            status_code=500
        )


if __name__ == "__main__":
    import uvicorn  
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)