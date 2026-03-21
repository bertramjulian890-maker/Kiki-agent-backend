from langgraph.prebuilt import ToolNode
from tools import TOOLS

# 使用 LangGraph 原生的 ToolNode 来自动执行工具调用
# 它能够自动从消息流中读取 ToolCall 请求并将其派发到注册的工具函数中执行
# 执行完毕后会将 ToolMessage 附加到状态中
tool_node_func = ToolNode(TOOLS)
