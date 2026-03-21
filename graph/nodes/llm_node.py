from typing import Dict, Any
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from graph.state import AgentState
from services.llm import llm_service
from tools import TOOLS

SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手 Kiki。你的回答应该：
- 简洁、贴心且友善
- 避免过于机械的表达
- 适当使用 emoji 增加温度
- 在不确定时诚实告知，不编造信息
- 若涉及需要查询的信息（如天气等），你可以自动调用相关工具获取
"""

async def llm_node_func(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    负责调用大语言模型进行推理的核心节点
    它会自动接收状态中的历史 messages，并将可使用的 Tools 绑定到 LLM。
    """
    messages = state["messages"]
    
    # 注入系统提示词
    full_messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    
    # 将工具列表绑定给当前的 LLM 模型实例
    model_with_tools = llm_service.model.bind_tools(TOOLS)
    
    # 执行推理，必须透传 config 以便 FastAPI 抛出 SSE Stream 流数据
    response = await model_with_tools.ainvoke(full_messages, config=config)
    
    return {"messages": [response]}
