import os
import json
import asyncio
from typing import Optional, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver

# 导入你自己的模块
from graph.state import AgentState
from graph.nodes import call_model, should_continue
from services.llm import llm_service
from graph.builder import create_agent_graph

# 加载环境变量
load_dotenv()

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

# === 统一创建 FastAPI 应用 ===
app = FastAPI(
    title="Personal Agent API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan
)

# === CORS 配置 (极其重要) ===
# 部署初期建议 allow_origins=["*"] 防止 Vercel 跨域报错
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建 Agent Graph 单例
agent_graph = create_agent_graph()
memory_saver = MemorySaver()

@app.get("/api/v1/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "agent": "ready"
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

@app.post("/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口（token 级输出）"""
    try:
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        user_message = HumanMessage(content=request.message)
        config = {
            "configurable": {
                "thread_id": request.conversation_id or "default"
            }
        }
        
        async def generate():
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': config['configurable']['thread_id']})}\n\n"
            
            full_response = ""
            messages = [SystemMessage(content=SYSTEM_PROMPT), user_message]
            
            async for chunk in llm_service.model.astream(messages):
                content = chunk.content or ""
                full_response += content
                yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                await asyncio.sleep(0.05)
            
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