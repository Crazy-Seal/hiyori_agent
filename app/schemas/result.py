from pydantic import BaseModel

class Result(BaseModel):
    # 结果包装类
    data: object
    msg: str
    code: int