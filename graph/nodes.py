from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from graph.state import AgentState
from services.llm import llm_service

# 系统提示词
SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手。你的回答应该：
- 简洁但友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
"""

async def call_model(state: AgentState) -> Dict[str, Any]:
    """
    核心节点：调用 LLM 生成回复
    
    这是最简单的实现，后续会扩展：
    - 添加工具调用
    - 添加 RAG 检索
    - 添加记忆检索
    """
    messages = state["messages"]
    
    # 在消息列表开头插入系统提示
    full_messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    
    # 调用 LLM（非流式，用于 Graph 节点）
    response = await llm_service.model.ainvoke(full_messages)
    
    # 返回要添加到 state 的更新
    return {
        "messages": [response],
        "next_action": "end"  # 简单实现，直接结束
    }

def should_continue(state: AgentState) -> str:
    """
    条件边：决定下一步走向
    
    当前简单实现，总是结束
    后续会扩展为：
    - 需要工具调用 -> 去工具节点
    - 需要检索 -> 去 RAG 节点
    - 完成 -> 结束
    """
    return "end"

# 节点映射（用于 builder）
NODES = {
    "call_model": call_model,
}