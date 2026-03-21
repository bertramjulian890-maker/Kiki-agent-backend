from .search import fake_weather_search

# 向外暴露所有供 LLM 调用的工具
TOOLS = [
    fake_weather_search
]
