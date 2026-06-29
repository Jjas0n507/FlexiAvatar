"""
工具系统抽象基类。

每个工具 = Pydantic 参数模型 + 执行函数。
通过装饰器/继承自动注册到 ToolRegistry。
参数自动转换为 LLM function-calling JSON Schema。
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Tool(ABC):
    """
    工具抽象基类。

    子类必须定义:
    - name: 工具唯一名称 (str)
    - description: 自然语言描述，告诉 LLM 什么时候用这个工具 (str)
    - parameters_model(): 返回 Pydantic 参数模型类
    - execute(): 实际执行逻辑

    用法示例:
        class TimeParams(BaseModel):
            timezone: str = Field(default="Asia/Shanghai", description="时区")

        class TimeTool(Tool):
            name = "get_current_time"
            description = "获取当前日期和时间"

            def parameters_model(self):
                return TimeParams

            async def execute(self, timezone="Asia/Shanghai"):
                from datetime import datetime
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    """

    # 子类必须定义
    name: str
    description: str

    @abstractmethod
    def parameters_model(self) -> type[BaseModel]:
        """返回 Pydantic 参数模型类"""
        ...

    @abstractmethod
    async def execute(self, **params) -> str:
        """
        执行工具逻辑。

        Args:
            **params: 已经过 Pydantic 校验的参数

        Returns:
            文本格式的执行结果
        """
        ...

    # ── 自动生成 ──────────────────────────────────

    @property
    def parameters_schema(self) -> dict:
        """
        从 Pydantic 模型自动生成 OpenAI function-calling 格式的 JSON Schema。
        """
        model = self.parameters_model()
        schema = model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }

    @property
    def is_async(self) -> bool:
        """自动检测 execute 是否是 async generator"""
        import inspect
        return inspect.iscoroutinefunction(self.execute)

    def __repr__(self) -> str:
        return f"Tool(name={self.name})"
