import os
from typing import Optional
from langchain_openai import ChatOpenAI  # 改用 OpenAI 兼容接口
from langchain_core.language_models.chat_models import BaseChatModel
from dotenv import load_dotenv

load_dotenv()

class LLMService:
    """LLM 服务封装，支持多模型切换（适配 API 中转站）"""
    
    _instance: Optional['LLMService'] = None
    _model: Optional[BaseChatModel] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """根据环境变量初始化默认模型"""
        default_model = os.getenv("DEFAULT_MODEL", "gpt").lower()
        
        if default_model == "gemini":
            self._model = self._create_gemini()
        elif default_model == "claude":
            self._model = self._create_claude()
        elif default_model == "gpt":
            self._model = self._create_gpt()
        else:
            raise ValueError(f"Unsupported model: {default_model}")
    
    def _create_gemini(self) -> ChatOpenAI:
        """通过中转站调用 Gemini"""
        api_key = os.getenv("GEMINI_API_KEY")
        base_url = os.getenv("GEMINI_BASE_URL")
        
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
        if not base_url:
            raise ValueError("GEMINI_BASE_URL not found in environment (中转站地址必填)")
        
        return ChatOpenAI(
            model="gemini-1.5-flash-latest",
            api_key=api_key,
            base_url=base_url,
            temperature=0.7,
            streaming=True,
        )
    
    def _create_claude(self) -> ChatOpenAI:
        """通过中转站调用 Claude"""
        api_key = os.getenv("CLAUDE_API_KEY")
        base_url = os.getenv("CLAUDE_BASE_URL")
        
        if not api_key:
            raise ValueError("CLAUDE_API_KEY not found in environment")
        if not base_url:
            raise ValueError("CLAUDE_BASE_URL not found in environment (中转站地址必填)")
        
        return ChatOpenAI(
            model="claude-sonnet-4-6",
            api_key=api_key,
            base_url=base_url,
            temperature=0.7,
            streaming=True,
        )

    def _create_gpt(self) -> ChatOpenAI:
        """通过中转站调用 GPT"""
        api_key = os.getenv("GPT_API_KEY")
        base_url = os.getenv("GPT_BASE_URL")
        
        if not api_key:
            raise ValueError("GPT_API_KEY not found in environment")
        if not base_url:
            raise ValueError("GPT_BASE_URL not found in environment (中转站地址必填)")
        
        return ChatOpenAI(
            model="gpt-4.1-nano-2025-04-14",
            api_key=api_key,
            base_url=base_url,
            temperature=0.7,
            streaming=True,
        )
    
    @property
    def model(self) -> BaseChatModel:
        """获取当前模型实例"""
        return self._model
    
    async def astream(self, messages: list):
        """流式生成接口"""
        async for chunk in self._model.astream(messages):
            yield chunk

# 全局单例
llm_service = LLMService()