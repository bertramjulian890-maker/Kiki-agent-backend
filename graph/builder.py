from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import AgentState
from graph.nodes.llm_node import llm_node_func
from graph.nodes.tool_node import tool_node_func
from graph.edges.routing import should_continue

def create_agent_graph(checkpointer=None):
    """
    组装并编译重构后的模块化 LangGraph 工作流
    """
    
    # 实例化基于 AgentState 数据结构的图模型
    workflow = StateGraph(AgentState)
    
    # 添加功能节点
    workflow.add_node("llm", llm_node_func)
    workflow.add_node("tools", tool_node_func)
    
    # 设置工作流入口
    workflow.add_edge(START, "llm")
    
    # 挂载条件分发：大模型回答完后决定下一步去哪
    workflow.add_conditional_edges(
        "llm",
        should_continue,
        {
            "tools": "tools",  # 如果有工具调用，跳去工具节点
            END: END           # 如果没有，直接结束，准备产出
        }
    )
    
    # 工具节点执行完后，必须回流给大模型，让大模型阅读工具产生的结果以进行最终总结
    workflow.add_edge("tools", "llm")
    
    # 为无数据库环境备底
    if checkpointer is None:
        checkpointer = MemorySaver()
        
    # 编译并挂载记忆系统
    app = workflow.compile(checkpointer=checkpointer)
    return app