from fastapi import APIRouter

from app.schemas.result import Result

router = APIRouter(tags=["plugins"])


@router.get("/plugins", response_model=Result)
def list_plugins() -> Result:
    """获取所有可用插件及其配置元数据。"""
    from app.agent.plugins.registry import PluginRegistry

    plugin_list: list[dict] = []
    for name in PluginRegistry.list_plugins():
        plugin_class = PluginRegistry.get(name)
        if plugin_class is None:
            continue
        config_model = getattr(plugin_class, "config_model", None)
        if config_model is not None:
            default_config = config_model().model_dump()
            config_schema = config_model.model_json_schema()
        else:
            default_config = {}
            config_schema = {"type": "object", "properties": {}}

        plugin_list.append({
            "name": getattr(plugin_class, "name", name),
            "description": getattr(plugin_class, "description", "") or "",
            "inherent": bool(getattr(plugin_class, "inherent", False)),
            "default_config": default_config,
            "config_schema": config_schema,
        })

    return Result(data={"plugins": plugin_list}, msg="success", code=200)
