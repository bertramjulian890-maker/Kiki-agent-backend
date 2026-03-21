from langchain_core.tools import tool

@tool
def fake_weather_search(city: str) -> str:
    """查询指定城市的天气情况"""
    # 这里是一个演示用的工具，后续可替换为对接真实 API (如高德/和风)
    if "北京" in city:
        return f"{city}的天气是晴朗，气温 25 度"
    elif "上海" in city:
        return f"{city}的天气是多云，气温 22 度"
    return f"{city}的天气未知，大概是个好天气！"
