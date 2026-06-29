"""
工具注册中心。

管理所有可用工具的注册、发现和调用。
支持：
- 内置工具自动发现 (builtin/ 目录)
- 用户工具热加载 (user_tools/ 目录)
- 为 LLM 生成 function-calling schema
"""

import importlib
import importlib.util
import pkgutil
from pathlib import Path

from backend.tools.base import Tool


class ToolRegistry:
    """全局工具注册中心（单例）"""

    _instance: "ToolRegistry | None" = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_tools"):
            return
        self._tools: dict[str, Tool] = {}
        self._loaded: bool = False

    # ── 注册 / 获取 ──────────────────────────────

    def register(self, tool: Tool) -> None:
        """注册一个工具实例"""
        if tool.name in self._tools:
            raise ValueError(f"工具 '{tool.name}' 已注册")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """注销一个工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        """获取指定工具"""
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未找到。可用工具: {list(self._tools.keys())}")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        """返回所有已注册工具的名称"""
        return list(self._tools.keys())

    def get_all(self) -> dict[str, Tool]:
        """返回所有工具的字典副本"""
        return dict(self._tools)

    # ── LLM Schema 生成 ──────────────────────────

    def get_all_schemas(self) -> list[dict]:
        """
        返回所有工具的函数调用 schema（OpenAI function-calling 格式）。
        直接传给 LLM 的 tools 参数。
        """
        return [tool.parameters_schema for tool in self._tools.values()]

    def get_llm_tools_description(self) -> str:
        """
        为不支持原生 function calling 的 LLM 生成文本格式的工具描述。
        可作为 system prompt 的一部分注入。
        """
        if not self._tools:
            return ""

        lines = ["可用工具："]
        for tool in self._tools.values():
            model = tool.parameters_model()
            schema = model.model_json_schema()
            props = schema.get("properties", {})
            params_desc = ", ".join(
                f"{k}: {v.get('description', '')} (类型: {v.get('type', 'any')})"
                for k, v in props.items()
            )
            lines.append(f"- {tool.name}: {tool.description}")
            if params_desc:
                lines.append(f"  参数: {params_desc}")
        return "\n".join(lines)

    # ── 自动发现 ──────────────────────────────────

    def discover_builtin_tools(self) -> int:
        """自动发现并注册 backend/tools/builtin/ 下的所有工具"""
        try:
            import backend.tools.builtin as builtin_pkg
        except ImportError:
            return 0

        count = 0
        builtin_path = Path(builtin_pkg.__path__[0]) if hasattr(builtin_pkg, '__path__') else None
        if not builtin_path:
            return 0

        for py_file in builtin_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = f"backend.tools.builtin.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                        self.register(attr())
                        count += 1
            except Exception as e:
                import logging
                logging.getLogger("tools").warning(f"加载内置工具 {module_name} 失败: {e}")

        return count

    def discover_user_tools(self, user_dir: str | Path | None = None) -> int:
        """自动发现并注册 user_tools/ 目录下的用户自定义工具"""
        if user_dir is None:
            from backend.config import config
            user_dir = config.get("tools.user_tools_dir", "backend/tools/user_tools")

        user_dir = Path(user_dir)
        if not user_dir.exists():
            return 0

        count = 0
        for py_file in user_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name.startswith("."):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"user_tool_{py_file.stem}", str(py_file)
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, Tool) and attr is not Tool:
                        self.register(attr())
                        count += 1
            except Exception as e:
                import logging
                logging.getLogger("tools").warning(f"加载用户工具 {py_file} 失败: {e}")

        return count

    def load_all(self, user_dir: str | Path | None = None) -> int:
        """加载所有工具（内置 + 用户）"""
        if self._loaded:
            return len(self._tools)
        self._loaded = True
        builtin_count = self.discover_builtin_tools()
        user_count = self.discover_user_tools(user_dir)
        return builtin_count + user_count

    # ── 执行 ──────────────────────────────────────

    async def execute_tool(self, name: str, **params) -> str:
        """
        查找并执行指定工具。

        Args:
            name: 工具名称
            **params: 工具参数（原始值，会通过 Pydantic 校验）

        Returns:
            工具执行的文本结果
        """
        tool = self.get(name)
        try:
            # Pydantic 参数校验
            param_model = tool.parameters_model()
            validated = param_model(**params)

            # 执行
            result = await tool.execute(**validated.model_dump())
            return str(result)
        except Exception as e:
            import logging
            logging.getLogger("tools").error(f"执行工具 {name} 失败: {e}")
            return f"工具执行出错: {e}"

    def reset(self) -> None:
        """重置注册中心（测试用）"""
        self._tools.clear()
        self._loaded = False
