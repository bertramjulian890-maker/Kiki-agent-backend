from langgraph.graph import END
from graph.state import AgentState

def should_continue(state: AgentState) -> str:
    """
    条件边路由逻辑：检查模型生成的最后一条消息，推断下一步往哪走
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # 如果大模型在其最新回复中附加了 tool_calls，则跳转到 "tools" 节点
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
        
    # 如果无需处理任务，直接走向图的终点 END
    return END
