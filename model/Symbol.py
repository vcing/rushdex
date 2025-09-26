from pydantic import BaseModel


class Symbol(BaseModel):
    """
    交易对数据类
    """
    symbol: str
    tick_size: str | None = None
    step_size: str | None = None
