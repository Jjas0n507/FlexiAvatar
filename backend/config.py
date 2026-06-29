"""
全局配置管理模块。

加载优先级: 环境变量 > config.user.yaml > config.default.yaml
敏感信息 (API Key 等) 只通过环境变量读取。
"""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


def _resolve_env(value: str) -> str:
    """解析 ${VAR_NAME} 格式的环境变量引用"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        return os.getenv(var_name, "")
    return value


def _resolve_env_recursive(obj: Any) -> Any:
    """递归解析配置中的环境变量引用"""
    if isinstance(obj, dict):
        return {k: _resolve_env_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_recursive(item) for item in obj]
    return _resolve_env(obj)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """全局配置单例"""

    _instance: "Config | None" = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_loaded"):
            return
        self._loaded = True
        self._data: dict = {}

    def load(self, default_path: str | Path = "config.default.yaml",
             user_path: str | Path = "config.user.yaml") -> "Config":
        """加载配置文件"""
        base_dir = Path(__file__).parent

        # 加载默认配置
        default_file = base_dir / default_path
        if default_file.exists():
            with open(default_file, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

        # 合并用户配置
        user_file = base_dir / user_path
        if user_file.exists():
            with open(user_file, "r", encoding="utf-8") as f:
                user_data = yaml.safe_load(f) or {}
            self._data = _deep_merge(self._data, user_data)

        # 解析环境变量引用
        self._data = _resolve_env_recursive(self._data)
        return self

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        通过点号分隔的路径获取配置值。
        例如: config.get("llm.openai.model")
        """
        keys = key_path.split(".")
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any) -> None:
        """通过点号路径设置配置值（运行时修改，不持久化）"""
        keys = key_path.split(".")
        target = self._data
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value

    def to_dict(self) -> dict:
        """返回配置的完整字典副本"""
        import copy
        return copy.deepcopy(self._data)


# 全局配置实例
config = Config()
