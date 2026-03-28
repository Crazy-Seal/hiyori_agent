from pydantic import BaseModel

class ChatSettings(BaseModel):
    # 会话 ID，用于区分前端不同的助手
    session_id: str
    # 大模型名称（OpenAI 兼容接口）
    model_name: str
    # 大模型 API Key
    openai_api_key: str
    # 可选：OpenAI 兼容网关地址（例如第三方平台）
    openai_base_url: str
    # 模型温度
    temperature: float
    # 系统提示词
    system_prompt: str
    # 工具列表
    tools_list: list[str]

    def __hash__(self):
        return hash((self.session_id,
                     self.model_name,
                     self.openai_api_key,
                     self.openai_base_url,
                     self.temperature,
                     # 不管system_prompt内容，只要配置和工具列表相同就认为是同一个模型配置（因为系统提示词经常调整）
                     # self.system_prompt,
                     tuple(self.tools_list)))