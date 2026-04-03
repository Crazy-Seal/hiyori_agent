from importlib import import_module


# 主图工具：使用"模块路径:符号名"做延迟加载，避免包初始化阶段的循环依赖。
TOOLS_REGISTRY = {
    "search_memory": "app.agent.tools.search_memory:search_memory",
    "access_the_internet": "app.agent.tools.access_the_internet:access_the_internet",
    "plan_and_coding": "app.agent.tools.plan_and_coding:plan_and_coding",
    "run_ps": "app.agent.tools.run_ps:run_ps",
    "read_file": "app.agent.tools.read_file:read_file",
    "write_file": "app.agent.tools.write_file:write_file",
    "edit_file": "app.agent.tools.edit_file:edit_file",
    "delete_file": "app.agent.tools.delete_file:delete_file",
}

# 编程子图工具：同样走延迟加载，集中在 tools 包统一维护。
SUBGRAPH_TOOLS_REGISTRY = {
    "run_ps": "app.agent.tools.run_ps:run_ps",
    "read_file": "app.agent.tools.read_file:read_file",
    "write_file": "app.agent.tools.write_file:write_file",
    "edit_file": "app.agent.tools.edit_file:edit_file",
    "delete_file": "app.agent.tools.delete_file:delete_file",
    "update_plan": "app.agent.tools.update_plan:update_plan",
}


def _resolve_tool(spec: str):
    """按规范字符串动态导入并返回工具对象。"""
    module_path, symbol = spec.split(":", 1)
    module = import_module(module_path)
    return getattr(module, symbol)


def get_tools(tool_names: list[str] | None = None):
    # 未指定名称时返回全部工具；指定后按配置顺序过滤。
    names = list(TOOLS_REGISTRY.keys()) if tool_names is None else [n for n in tool_names if n in TOOLS_REGISTRY]
    return [_resolve_tool(TOOLS_REGISTRY[name]) for name in names]


def get_subgraph_tools(tool_names: list[str] | None = None):
    # 未指定名称时返回全部子图工具；指定后按配置顺序过滤。
    names = (
        list(SUBGRAPH_TOOLS_REGISTRY.keys())
        if tool_names is None
        else [n for n in tool_names if n in SUBGRAPH_TOOLS_REGISTRY]
    )
    return [_resolve_tool(SUBGRAPH_TOOLS_REGISTRY[name]) for name in names]
