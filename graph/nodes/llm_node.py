import os
from typing import Dict, Any
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from graph.state import AgentState
from services.llm import llm_service
from tools import TOOLS

_SKILLS_PROMPT_CACHE = None

def get_skills_prompt() -> str:
    """动态读取 skills 目录下的所有技能文档并拼接成 prompt，使用缓存避免频繁读盘"""
    global _SKILLS_PROMPT_CACHE
    if _SKILLS_PROMPT_CACHE is not None:
        return _SKILLS_PROMPT_CACHE

    # 基于当前文件路径计算出项目根目录下的 skills/ 目录路径
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    skills_dir = os.path.join(base_dir, "skills")

    prompt = ""
    if os.path.exists(skills_dir):
        for filename in os.listdir(skills_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(skills_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        prompt += f"\n\n--- Skill: {filename} ---\n{content}\n"
                except Exception as e:
                    print(f"Error reading skill file {filename}: {e}")

    _SKILLS_PROMPT_CACHE = prompt
    return prompt

BASE_SYSTEM_PROMPT = """你是一个温暖、贴心的AI助手 Kiki。你的回答应该：
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
    # 动态加载所有 skills
    skills_prompt = get_skills_prompt()
    system_prompt = BASE_SYSTEM_PROMPT
    if skills_prompt:
        system_prompt += "\n\n你具备以下网易云音乐相关技能，可以使用 shell 命令执行相应的操作：\n" + skills_prompt

    full_messages = [SystemMessage(content=system_prompt)] + list(messages)
    
    # 将工具列表绑定给当前的 LLM 模型实例
    model_with_tools = llm_service.model.bind_tools(TOOLS)
    
    # 执行推理，必须透传 config 以便 FastAPI 抛出 SSE Stream 流数据
    response = await model_with_tools.ainvoke(full_messages, config=config)
    
    return {"messages": [response]}
