from typing import Optional
from pydantic import BaseModel
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import json
import os
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage

from fastapi.responses import JSONResponse

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from graph.state import AgentState
from graph.nodes import call_model, should_continue
from services.llm import llm_service
from graph.builder import create_agent_graph
import json
import asyncio

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

app = FastAPI(
    title="Personal Agent API",
    version="0.1.0",
    default_response_class=UTF8JSONResponse  # 全局使用 UTF-8
)

# 创建 Agent Graph 单例
agent_graph = create_agent_graph()
memory_saver = MemorySaver()


# 加载环境变量
load_dotenv()

# 系统提示词
SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手。你的回答应该：
- 简洁但友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
"""

# 导入 Graph
from graph.builder import agent_graph
from langchain_core.messages import HumanMessage

# 请求模型
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

class Message(BaseModel):
    role: str
    content: str

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    print("🚀 Agent 启动中...")
    yield
    # 关闭时
    print("👋 Agent 已关闭")

# 创建应用
app = FastAPI(
    title="Personal Agent API",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    """
    非流式对话接口（用于测试）
    后续会被流式接口替代
    """
    try:
        # 创建 HumanMessage
        message = HumanMessage(content=request.message)
        
        # 调用 Graph
        # config 用于传递 thread_id（对话隔离）和 checkpointer
        config = {
            "configurable": {
                "thread_id": request.conversation_id or "default"
            }
        }
        
        # 运行图
        result = await agent_graph.ainvoke(
            {"messages": [message]},
            config
        )
        
        # 提取 AI 回复
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        if ai_messages:
            response_content = ai_messages[-1].content
        else:
            response_content = "抱歉，我没有生成回复。"
        
        return {
            "success": True,
            "response": response_content,
            "conversation_id": request.conversation_id or "default"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口（token 级输出）"""
    try:
        # 验证输入
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # 准备消息
        user_message = HumanMessage(content=request.message)
        config = {
            "configurable": {
                "thread_id": request.conversation_id or "default"
            }
        }
        
        # 流式处理生成器
        async def generate():
            # 发送开始标记
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': config['configurable']['thread_id']})}\n\n"
            
            # 使用流式调用 LLM
            full_response = ""
            
            # 构造完整的消息列表（系统提示 + 历史消息 + 当前消息）
            # 简化实现，直接调用 LLM 而不是通过 Graph（为了更好的流式效果）
            messages = [SystemMessage(content=SYSTEM_PROMPT), user_message]
            
            # 直接调用 LLM 的 astream 方法
            async for chunk in llm_service.model.astream(messages):
                content = chunk.content or ""
                full_response += content
                
                # 发送 chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                
                # 延迟模拟打字机效果
                await asyncio.sleep(0.05)
            
            # 发送结束标记
            yield f"data: {json.dumps({'type': 'end', 'fullResponse': full_response})}\n\n"
            
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*"
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
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)