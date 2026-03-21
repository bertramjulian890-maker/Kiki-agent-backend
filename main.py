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

from psycopg_pool import ConnectionPool
from langchain_postgres import PostgresChatMessageHistory
from langgraph.checkpoint.postgres import PostgresSaver

from graph.state import AgentState
from graph.nodes import call_model, should_continue
from services.llm import llm_service
from graph.builder import create_agent_graph

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
pool = None
checkpointer = None
agent_graph = None 

# 2. 数据库逻辑
if DB_URL:
    try:
        pool = ConnectionPool(
            conninfo=DB_URL, 
            max_size=20, 
            kwargs={
                "autocommit": True,  # 👈 必须为 True
                "prepare_threshold": None
            }
        )
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        # 3. 关键：将带存储的 checkpointer 注入
        agent_graph = create_agent_graph(checkpointer)
        print("✅ 成功启动：Supabase 持久化模式")
    except Exception as e:
        print(f"❌ 数据库连接失败，切换到内存模式: {e}")
        agent_graph = create_agent_graph(None)
else:
    # 4. 兜底
    agent_graph = create_agent_graph(None)
    print("⚠️ 运行模式：仅内存存储")

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

# 💡 新增：将前端的非标准 ID 转换为标准 UUID 的魔法函数
def ensure_uuid(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except ValueError:
        # 使用 uuid5 将任何字符串稳定地映射为一个标准 UUID
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Agent 启动中...")
    if pool:
        try:
            with pool.connection() as conn:
                PostgresChatMessageHistory.create_tables(conn, "chat_history")
            print("✅ Supabase chat_history 表就绪！")
        except Exception as e:
            print(f"⚠️ 检查/创建 chat_history 表时出现提示: {e}")
            
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
        
        # 1. 拿到前端的原始 ID
        original_session_id = request.conversation_id or "default"
        # 2. 转换成数据库/Checkpointer 接受的标准 UUID
        db_session_id = ensure_uuid(original_session_id)
        
        user_message = HumanMessage(content=request.message)
        
        # 3. 构造 LangGraph 的配置 (通过 thread_id 自动关联历史记忆)
        config = {
            "configurable": {
                "thread_id": db_session_id
            }
        }

        async def generate():
            # 告诉前端流式传输开始
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': original_session_id}, ensure_ascii=False)}\n\n"
            
            full_response = ""
            
            try:
                # --- 核心重构：调用 agent_graph 替代 direct LLM 调用 ---
                # 使用推荐的 astream_events (v2 版本) 监听图中发生的所有事件
                async for event in agent_graph.astream_events(
                    {"messages": [user_message]},
                    config=config,
                    version="v2"
                ):
                    kind = event["event"]
                    name = event["name"]
                    
                    # (1) 捕获节点流转：进入 call_model 节点
                    if kind == "on_chain_start" and name == "call_model":
                        yield f"data: {json.dumps({'type': 'event', 'status': 'thinking', 'message': 'Kiki 正在思考...'}, ensure_ascii=False)}\n\n"
                    
                    # (2) 捕获 token 生成：大模型文字流式输出
                    elif kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        # 确保有实际内容再拼接和下发
                        if chunk.content:
                            full_response += chunk.content
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                            
                    # (3) 预留 Tool 壳子：工具调用开始
                    elif kind == "on_tool_start":
                        tool_input = event["data"].get("input", "")
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'tool_input': tool_input, 'status': 'running'}, ensure_ascii=False)}\n\n"
                        
                    # (4) 预留 Tool 壳子：工具调用结束
                    elif kind == "on_tool_end":
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'status': 'completed'}, ensure_ascii=False)}\n\n"

                    pass
                print(f"--- 尝试检查 thread_id: {db_session_id} 的状态 ---")
                snapshot = await agent_graph.aget_state(config) # 注意：异步环境下建议使用 aget_state
                # 2. 打印时直接访问 values
                if snapshot and snapshot.values:
                    print(f"--- 内存中读取到的消息数: {len(snapshot.values.get('messages', []))} ---")
                else:
                    print("--- 当前 thread_id 下无任何状态记录 ---")       

            except Exception as stream_e:
                # 捕获图运行时的内部错误
                error_data = {
                    "type": "error",
                    "message": str(stream_e),
                    "conversation_id": original_session_id
                }
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                return

            # 输出完整回复标识
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