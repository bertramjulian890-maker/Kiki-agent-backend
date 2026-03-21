from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from graph.state import AgentState
from graph.nodes import NODES, should_continue

def create_agent_graph(checkpointer=None):
    """
    创建并编译 Agent 图
    
    当前流程：
    START -> call_model -> END
    
    后续会扩展为：
    START -> call_model -> [需要工具?] -> tool_node -> call_model
                      -> [需要检索?] -> rag_node -> call_model
                      -> [完成] -> END
    """
    # 创建状态图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("call_model", NODES["call_model"])
    
    # 设置入口点
    workflow.set_entry_point("call_model")
    
    # 添加条件边
    workflow.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "end": END,
            "continue": "call_model"  # 预留，目前不会用到
        }
    )
    
    # 添加内存检查点（用于短期对话记忆）
    if checkpointer is None:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
        
        # 3. 编译时必须传入这个 checkpointer
    app = workflow.compile(checkpointer=checkpointer)
    return app

# 全局图实例
agent_graph = create_agent_graph()