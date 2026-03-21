import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from api.models import ChatRequest
from services.database import db_service

router = APIRouter(prefix="/api/v1")

def ensure_uuid(session_id: str) -> str:
    """确保 session_id 为合格的 UUID 格式，用于 checkpointer thread_id"""
    try:
        return str(uuid.UUID(session_id))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))

@router.get("/health")
async def health_check():
    """节点健康探测接口"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "agent": "ready",
        "database": "connected" if db_service.pool else "disconnected"
    }

@router.post("/chat")
async def chat_endpoint(chat_req: ChatRequest, request: Request):
    """
    基础对话接口 (非流式)
    符合 api_contract 规格
    """
    try:
        agent_graph = request.app.state.agent_graph
        message = HumanMessage(content=chat_req.message)
        original_session_id = chat_req.conversation_id or "default"
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

@router.post("/chat/stream")
async def chat_stream_endpoint(chat_req: ChatRequest, request: Request):
    """
    核心流式响应接口 (Server-Sent Events)
    解析 LangGraph 事件，产生与前端相连接的 chunk, tool, start, end 等状态。
    """
    try:
        if not chat_req.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        agent_graph = request.app.state.agent_graph
        original_session_id = chat_req.conversation_id or "default"
        db_session_id = ensure_uuid(original_session_id)
        
        user_message = HumanMessage(content=chat_req.message)
        
        config = {
            "configurable": {
                "thread_id": db_session_id
            }
        }

        async def generate() -> AsyncGenerator[str, None]:
            # 建立流式通信的起始点
            yield f"data: {json.dumps({'type': 'start', 'conversation_id': original_session_id}, ensure_ascii=False)}\n\n"
            
            full_response = ""
            
            try:
                # 消费 LangGraph V2 事件流
                async for event in agent_graph.astream_events(
                    {"messages": [user_message]},
                    config=config,
                    version="v2"
                ):
                    kind = event["event"]
                    name = event["name"]
                    
                    # 1. 大模型开始思考，对应 UI loading
                    if kind == "on_chain_start" and name == "llm":
                        yield f"data: {json.dumps({'type': 'event', 'status': 'thinking', 'message': 'Kiki 正在思考...'}, ensure_ascii=False)}\n\n"
                    
                    # 2. 文本增量生成，推送至前端打字机
                    elif kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            full_response += chunk.content
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"
                            
                    # 3. 工具执行开始
                    elif kind == "on_tool_start":
                        tool_input = event["data"].get("input", "")
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'tool_input': str(tool_input), 'status': 'running'}, ensure_ascii=False)}\n\n"
                        
                    # 4. 工具执行结束 (按照新版协议发送闭环)
                    elif kind == "on_tool_end":
                        # 工具产出结果也在 event['data'] 获取，未来优化时可提取以传给前端卡片
                        yield f"data: {json.dumps({'type': 'tool', 'tool_name': name, 'status': 'completed'}, ensure_ascii=False)}\n\n"

                # 若需检查保存条数等可在此处通过 agent_graph.aget_state 读取
                
            except Exception as stream_e:
                error_data = {
                    "type": "error",
                    "message": str(stream_e),
                    "conversation_id": original_session_id
                }
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                return

            # 图运行完时，给出闭环标志
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
            "conversation_id": chat_req.conversation_id or "default"
        }
        return StreamingResponse(
            [f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"],
            media_type="text/event-stream",
            status_code=500
        )
