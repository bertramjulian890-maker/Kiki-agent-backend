from typing import Annotated, TypedDict, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    LangGraph 的状态定义
    会自动在节点间传递
    """
    # messages: 对话历史（使用 add_messages 自动追加）
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # next_action: 用于条件路由（后续扩展用）
    next_action: str
    
    # context: 额外上下文信息
    context: dict