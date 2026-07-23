from pathlib import Path

import yaml

from app.runtime import get_mcp_settings_file
from app.schemas.mcp import MCPServersConfig


class MCPSettingsDao:
    """读写本地 MCP Server YAML 配置。"""

    def __init__(self, config_file: Path | None = None):
        """初始化 MCP 配置数据访问对象。

        Args:
            config_file: 可选的配置文件路径；未提供时使用运行环境默认路径。
        """
        self.config_file = config_file or get_mcp_settings_file()

    def load(self) -> MCPServersConfig:
        """加载并校验 MCP Server 配置。

        Returns:
            经过 Pydantic 校验的 MCP Server 配置；文件不存在时返回空配置。
        """
        if not self.config_file.exists():
            return MCPServersConfig()
        with self.config_file.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return MCPServersConfig.model_validate(data)

    def save(self, config: MCPServersConfig) -> MCPServersConfig:
        """通过临时文件原子保存 MCP Server 配置。

        Args:
            config: 待保存的 MCP Server 配置。

        Returns:
            已保存的原配置对象。
        """
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.config_file.with_suffix(f"{self.config_file.suffix}.tmp")
        with temp_file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(config.model_dump(mode="json"), file, allow_unicode=True, sort_keys=False)
        temp_file.replace(self.config_file)
        return config
