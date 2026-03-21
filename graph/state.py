from typing import Annotated, TypedDict, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    LangGraph 的核心状态字典 (State)
    会在不同节点(llm_node, tool_node等)之间流转，进行状态累积
    """
    # 核心字段：对话上下文历史
    # 使用 add_messages 取代覆盖，以支持历史追加机制
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 此处为后续 RAG 机制等扩展保留可能所需的元数据字典（可选）
    context: dict