import logging
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.config import settings

logger = logging.getLogger(__name__)

class DatabaseService:
    """管理 Postgres 数据库连接池以及 LangGraph Checkpointer 生命周期的服务"""
    
    def __init__(self):
        self.pool = None
        self.checkpointer = None

    async def connect(self):
        if settings.DATABASE_URL:
            try:
                self.pool = AsyncConnectionPool(
                    conninfo=settings.DATABASE_URL, 
                    max_size=20, 
                    kwargs={
                        "autocommit": True, 
                        "prepare_threshold": None
                    }
                )
                self.checkpointer = AsyncPostgresSaver(self.pool)
                # 初始化/校验 checkpointer 的必要数据库表
                await self.checkpointer.setup()
                print("✅ 成功启动：Supabase 全异步持久化模式！")
            except Exception as e:
                print(f"❌ 数据库连接失败，切换到内存模式: {e}")
                self.pool = None
                self.checkpointer = None
        else:
            print("⚠️ 运行模式：仅内存存储 (DATABASE_URL 未配置)")
            self.checkpointer = None

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
            print("👋 数据库连接池已正常关闭")

# 单例抛出
db_service = DatabaseService()
