import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Settings:
    """全局应用配置单例"""
    
    # 基础信息
    APP_NAME = "Personal Agent API"
    VERSION = "0.1.0"
    
    # 数据库连接池
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    
    # 模型配置
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude").lower()

settings = Settings()
